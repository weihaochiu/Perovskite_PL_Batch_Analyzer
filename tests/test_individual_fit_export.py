import json
from pathlib import Path
import tempfile
import unittest

import matplotlib
import numpy as np
import pandas as pd
from openpyxl import load_workbook

matplotlib.use("Agg")

from export_manager import ExportOptions, export_all, fit_curve_dataframe
from pl_core import HC_EV_NM, PLSpectrum, PeakResult, SpectrumFitResult, build_fit_curve_data
from plotting import selected_fit_figure


CSV_ONLY = ExportOptions(
    summary_excel=False,
    individual_csv=True,
    individual_excel=False,
    figures_png=False,
    figures_pdf=False,
)
CURVE_FILES = ExportOptions(
    summary_excel=False,
    individual_csv=True,
    individual_excel=True,
    figures_png=False,
    figures_pdf=False,
)


def make_row(output_name, *, n_peaks=1, model="Gaussian", source_name=None, baseline_mode="Constant"):
    energy = np.linspace(1.35, 1.85, 16)
    baseline = np.linspace(1.0, 1.5, len(energy)) if baseline_mode != "None" else np.zeros_like(energy)
    components = []
    peaks = []
    for index in range(1, n_peaks + 1):
        center = 1.4 + index * 0.1
        component = (10.0 * index) * np.exp(-4 * np.log(2) * ((energy - center) / 0.08) ** 2)
        components.append(component)
        peaks.append(
            PeakResult(
                peak_index=index,
                center_ev=center,
                center_nm=HC_EV_NM / center,
                fwhm_ev=0.08,
                fwhm_mev=80.0,
                height=10.0 * index,
                area=float(np.trapezoid(component, energy)),
                area_fraction=1.0 / n_peaks,
                parameters={},
                errors={},
            )
        )
    total_fit = baseline + np.sum(components, axis=0)
    residual = np.linspace(-0.25, 0.25, len(energy))
    raw = total_fit + residual
    source_name = source_name or f"{output_name}.asc"
    spectrum = PLSpectrum(
        wavelength_nm=HC_EV_NM / energy,
        photon_energy_ev=energy,
        intensity_wavelength=raw.copy(),
        intensity_energy=raw.copy(),
        temperature_k=300.0,
        condition="C1",
        sample_id="C1-1",
        source_name=source_name,
        metadata={},
    )
    result = SpectrumFitResult(
        temperature_k=300.0,
        model=model,
        n_peaks=n_peaks,
        peaks=peaks,
        x_ev=energy,
        y_raw=raw,
        y_fit=total_fit,
        components=components,
        baseline=baseline,
        residual=residual,
        r_squared=0.999,
        adjusted_r_squared=0.998,
        rmse=0.1,
        reduced_chi2=0.01,
        aic=1.0,
        aicc=2.0,
        bic=3.0,
        warnings=[],
        baseline_mode=baseline_mode,
    )
    return output_name, spectrum, result


def make_record(row, *, status="OK", failure_reason=""):
    label, spectrum, _ = row
    record = {
        "use": True,
        "export": True,
        "condition": spectrum.condition,
        "sample_id": spectrum.sample_id,
        "temperature": spectrum.temperature_k,
        "direction": "Isothermal",
        "code": label,
        "path": str(Path("input") / spectrum.source_name),
        "x": "Wavelength_nm",
        "y": "PL_Intensity",
        "status": status,
    }
    if failure_reason:
        record["failure_reason"] = failure_reason
    return record


def _check_one_peak_curve_has_required_columns_and_equal_lengths():
    result = make_row("one", n_peaks=1)[2]
    frame = fit_curve_dataframe(result)

    assert frame.columns.tolist() == [
        "Photon_Energy_eV",
        "Wavelength_nm",
        "Raw_Intensity",
        "Baseline",
        "Peak_1",
        "Total_Fit",
        "Residual",
    ]
    assert frame.notna().all().all()
    assert all(len(frame[column]) == len(result.x_ev) for column in frame.columns)
    np.testing.assert_allclose(frame["Residual"], frame["Raw_Intensity"] - frame["Total_Fit"])


def _check_all_models_and_supported_peak_counts_export_individual_components():
    for model in ["Gaussian", "Lorentzian", "Pseudo-Voigt", "Voigt"]:
        for n_peaks in [1, 2, 3]:
            frame = fit_curve_dataframe(make_row("multi", n_peaks=n_peaks, model=model)[2])
            assert [column for column in frame if column.startswith("Peak_")] == [
                f"Peak_{index}" for index in range(1, n_peaks + 1)
            ]
            for index in range(1, n_peaks + 1):
                assert not np.allclose(frame[f"Peak_{index}"], frame["Total_Fit"])


def _check_no_baseline_model_omits_baseline_column():
    frame = fit_curve_dataframe(make_row("none", baseline_mode="None")[2])
    assert "Baseline" not in frame.columns


def _check_79_successful_results_create_79_individual_csv_files(tmp_path):
    rows = [make_row(f"C{index + 1}", source_name=f"source_{index + 1}.asc") for index in range(79)]

    report = export_all(tmp_path, rows, {}, {}, options=CURVE_FILES)

    csv_files = list((tmp_path / "Individual_Fit_Data").glob("*.csv"))
    assert report["successful_curve_exports"] == 79
    assert report["csv_files"] == 79
    assert len(csv_files) == 79
    workbook = load_workbook(tmp_path / "Individual_Fitting_Data.xlsx", read_only=True)
    assert workbook.sheetnames[0] == "Index"
    assert len(workbook.sheetnames) == 80
    workbook.close()


def _check_duplicate_invalid_and_long_output_names_get_unique_safe_targets(tmp_path):
    long_name = "Long_Output_Name_" * 5
    rows = [
        make_row("sample", source_name="first.asc"),
        make_row("sample", source_name="second.asc"),
        make_row("A:B/C*D?", source_name="invalid.asc"),
        make_row(long_name, source_name="long.asc"),
    ]

    export_all(tmp_path, rows, {}, {}, options=CURVE_FILES)

    csv_names = sorted(path.name for path in (tmp_path / "Individual_Fit_Data").glob("*.csv"))
    assert "sample.csv" in csv_names
    assert "sample_2.csv" in csv_names
    assert "A_B_C_D_.csv" in csv_names
    assert len(csv_names) == 4
    assert all(not any(character in name for character in '<>:"/\\|?*') for name in csv_names)

    workbook = load_workbook(tmp_path / "Individual_Fitting_Data.xlsx", read_only=True)
    assert workbook.sheetnames[0] == "Index"
    assert len(workbook.sheetnames) == 5
    assert len({name.casefold() for name in workbook.sheetnames}) == 5
    assert all(len(name) <= 31 for name in workbook.sheetnames)
    workbook.close()
    index = pd.read_excel(tmp_path / "Individual_Fitting_Data.xlsx", sheet_name="Index")
    assert index["Output Name"].tolist() == ["sample", "sample", "A:B/C*D?", long_name]
    assert index["CSV_Filename"].tolist()[:3] == ["sample.csv", "sample_2.csv", "A_B_C_D_.csv"]
    assert index["CSV_Filename"].iloc[3] in csv_names
    assert index["CSV_Filename"].iloc[3].startswith("Long_Output_Name_")
    first_sheet = index["Export_Sheet_Name"].iloc[0]
    metadata = pd.read_excel(
        tmp_path / "Individual_Fitting_Data.xlsx", sheet_name=first_sheet, nrows=15
    )
    assert dict(zip(metadata["Metadata_Field"], metadata["Value"]))["Output Name"] == "sample"
    curve_table = pd.read_excel(
        tmp_path / "Individual_Fitting_Data.xlsx", sheet_name=first_sheet, header=17
    )
    assert curve_table.columns.tolist() == [
        "Photon_Energy_eV",
        "Wavelength_nm",
        "Raw_Intensity",
        "Baseline",
        "Peak_1",
        "Total_Fit",
        "Residual",
    ]


def _check_gui_curve_data_and_exported_dataframe_are_numerically_identical(tmp_path):
    row = make_row("identity", n_peaks=3)
    result = row[2]
    curves = build_fit_curve_data(result)
    frame = fit_curve_dataframe(result)
    figure = selected_fit_figure(result)

    plot_lines = {line.get_label(): line.get_ydata() for line in figure.axes[0].lines}
    np.testing.assert_allclose(plot_lines["Raw"], curves.raw_intensity)
    np.testing.assert_allclose(plot_lines["Total fit"], curves.total_fit)
    np.testing.assert_allclose(plot_lines["Baseline"], curves.baseline)
    for index, component in enumerate(curves.components, 1):
        np.testing.assert_allclose(plot_lines[f"Peak {index}"], component)
        np.testing.assert_allclose(frame[f"Peak_{index}"], component)
    np.testing.assert_allclose(figure.axes[1].lines[0].get_ydata(), curves.residual)
    np.testing.assert_allclose(frame["Raw_Intensity"], curves.raw_intensity)
    np.testing.assert_allclose(frame["Total_Fit"], curves.total_fit)
    np.testing.assert_allclose(frame["Residual"], curves.residual)

    export_all(tmp_path, [row], {}, {}, options=CSV_ONLY)
    csv_path = tmp_path / "Individual_Fit_Data" / "identity.csv"
    assert csv_path.read_bytes().startswith(b"\xef\xbb\xbf")
    exported = pd.read_csv(csv_path, encoding="utf-8-sig")
    for column in frame:
        np.testing.assert_allclose(exported[column], frame[column])
    figure.clear()


def _check_failed_fit_is_indexed_without_fake_curve_file(tmp_path):
    successful_rows = [
        make_row("good-1", source_name="good-1.asc"),
        make_row("good-2", source_name="good-2.asc"),
    ]
    records = [make_record(row) for row in successful_rows]
    failed_stub = make_row("bad", source_name="bad.asc")
    records.append(make_record(failed_stub, status="Failed", failure_reason="optimizer did not converge"))

    report = export_all(
        tmp_path,
        successful_rows,
        {},
        {},
        records=records,
        options=CURVE_FILES,
    )

    assert report == {"successful_curve_exports": 2, "csv_files": 2, "index_rows": 3}
    assert len(list((tmp_path / "Individual_Fit_Data").glob("*.csv"))) == 2
    assert not (tmp_path / "Individual_Fit_Data" / "bad.csv").exists()
    index = pd.read_excel(tmp_path / "Individual_Fitting_Data.xlsx", sheet_name="Index")
    failed = index.loc[index["Output Name"] == "bad"].iloc[0]
    assert failed["Fit_Status"] == "Failed"
    assert failed["Failure_Reason"] == "optimizer did not converge"
    assert pd.isna(failed["CSV_Filename"])
    manifest = json.loads((tmp_path / "Individual_Fit_Data" / "Index.json").read_text(encoding="utf-8"))
    assert next(row for row in manifest if row["Output Name"] == "bad")["Fit_Status"] == "Failed"


class TestIndividualFitExport(unittest.TestCase):
    def test_one_peak_curve_has_required_columns_and_equal_lengths(self):
        _check_one_peak_curve_has_required_columns_and_equal_lengths()

    def test_all_models_and_supported_peak_counts_export_individual_components(self):
        _check_all_models_and_supported_peak_counts_export_individual_components()

    def test_no_baseline_model_omits_baseline_column(self):
        _check_no_baseline_model_omits_baseline_column()

    def test_79_successful_results_create_79_individual_csv_files(self):
        with tempfile.TemporaryDirectory() as tmp:
            _check_79_successful_results_create_79_individual_csv_files(Path(tmp))

    def test_duplicate_invalid_and_long_output_names_get_unique_safe_targets(self):
        with tempfile.TemporaryDirectory() as tmp:
            _check_duplicate_invalid_and_long_output_names_get_unique_safe_targets(Path(tmp))

    def test_gui_curve_data_and_exported_dataframe_are_numerically_identical(self):
        with tempfile.TemporaryDirectory() as tmp:
            _check_gui_curve_data_and_exported_dataframe_are_numerically_identical(Path(tmp))

    def test_failed_fit_is_indexed_without_fake_curve_file(self):
        with tempfile.TemporaryDirectory() as tmp:
            _check_failed_fit_is_indexed_without_fake_curve_file(Path(tmp))


if __name__ == "__main__":
    unittest.main()

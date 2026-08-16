from __future__ import annotations

from dataclasses import dataclass
import json
from pathlib import Path
import re
from typing import Any

import numpy as np
import pandas as pd
from openpyxl.styles import Font, PatternFill
from openpyxl.utils import get_column_letter

from pl_core import build_fit_curve_data, result_to_dict


WINDOWS_FORBIDDEN = re.compile(r'[<>:"/\\|?*\x00-\x1f]')
EXCEL_FORBIDDEN = re.compile(r'[\[\]:*?/\\\x00-\x1f]')
WINDOWS_RESERVED = {
    "CON",
    "PRN",
    "AUX",
    "NUL",
    *(f"COM{index}" for index in range(1, 10)),
    *(f"LPT{index}" for index in range(1, 10)),
}


@dataclass(frozen=True)
class ExportOptions:
    summary_excel: bool = True
    individual_csv: bool = True
    individual_excel: bool = True
    figures_png: bool = True
    figures_pdf: bool = True


@dataclass
class _ExportEntry:
    output_name: str
    source_filename: str
    condition: str
    temperature: Any
    row: tuple | None
    fit_status: str
    failure_reason: str = ""
    csv_filename: str = ""
    sheet_name: str = ""


def _coerce_options(options: ExportOptions | dict[str, bool] | None) -> ExportOptions:
    if options is None:
        return ExportOptions()
    if isinstance(options, ExportOptions):
        return options
    return ExportOptions(**options)


def sanitize_windows_filename(value: str, *, maximum_length: int = 150) -> str:
    """Sanitize an export filename without changing the source Output Name."""
    name = WINDOWS_FORBIDDEN.sub("_", str(value)).strip().rstrip(". ")
    if name.lower().endswith(".csv"):
        name = name[:-4].rstrip(". ")
    name = name[:maximum_length].rstrip(". ") or "spectrum"
    if name.upper() in WINDOWS_RESERVED:
        name = f"{name}_"
    return name


def unique_csv_filename(output_name: str, used_names: set[str]) -> str:
    base = sanitize_windows_filename(output_name)
    candidate = f"{base}.csv"
    suffix = 2
    while candidate.casefold() in used_names:
        suffix_text = f"_{suffix}"
        candidate = f"{base[:150-len(suffix_text)].rstrip()}{suffix_text}.csv"
        suffix += 1
    used_names.add(candidate.casefold())
    return candidate


def unique_excel_sheet_name(value: str, used_names: set[str]) -> str:
    base = EXCEL_FORBIDDEN.sub("_", str(value)).strip().strip("'") or "Fit"
    base = base[:31]
    candidate = base
    suffix = 2
    while candidate.casefold() in used_names:
        suffix_text = f"_{suffix}"
        candidate = f"{base[:31-len(suffix_text)].rstrip()}{suffix_text}"
        suffix += 1
    used_names.add(candidate.casefold())
    return candidate


def fit_curve_dataframe(result) -> pd.DataFrame:
    """Build an Origin-friendly table from the shared saved curve arrays."""
    curves = build_fit_curve_data(result)
    data = {
        "Photon_Energy_eV": curves.photon_energy_ev,
        "Wavelength_nm": curves.wavelength_nm,
        "Raw_Intensity": curves.raw_intensity,
    }
    if curves.baseline is not None:
        data["Baseline"] = curves.baseline
    for index, component in enumerate(curves.components, 1):
        data[f"Peak_{index}"] = component
    data["Total_Fit"] = curves.total_fit
    data["Residual"] = curves.residual
    return pd.DataFrame(data)


def _find_matching_row(record, remaining_rows):
    output_name = str(record.get("code", ""))
    source_filename = Path(str(record.get("path", ""))).name
    if source_filename:
        for index, row in enumerate(remaining_rows):
            if str(row[1].source_name) == source_filename:
                return remaining_rows.pop(index)
    for index, row in enumerate(remaining_rows):
        if str(row[0]) == output_name:
            return remaining_rows.pop(index)
    return None


def _build_entries(rows, records=None):
    remaining_rows = list(rows)
    entries = []
    if records is not None:
        for record in records:
            row = _find_matching_row(record, remaining_rows)
            if not record.get("export", True):
                continue
            if row is not None:
                _, spectrum, _ = row
                entries.append(
                    _ExportEntry(
                        output_name=str(record.get("code", row[0])),
                        source_filename=spectrum.source_name,
                        condition=spectrum.condition,
                        temperature=spectrum.temperature_k,
                        row=row,
                        fit_status="Successful",
                    )
                )
                continue
            status = str(record.get("status", ""))
            entries.append(
                _ExportEntry(
                    output_name=str(record.get("code", "")),
                    source_filename=Path(str(record.get("path", ""))).name,
                    condition=str(record.get("condition", "")),
                    temperature=record.get("temperature", ""),
                    row=None,
                    fit_status="Failed" if status.casefold() == "failed" else (status or "Not fitted"),
                    failure_reason=str(record.get("failure_reason", "")),
                )
            )

    for label, spectrum, result in remaining_rows:
        entries.append(
            _ExportEntry(
                output_name=str(label),
                source_filename=spectrum.source_name,
                condition=spectrum.condition,
                temperature=spectrum.temperature_k,
                row=(label, spectrum, result),
                fit_status="Successful",
            )
        )
    return entries


def _index_rows(entries):
    output = []
    for entry in entries:
        result = entry.row[2] if entry.row is not None else None
        output.append(
            {
                "Output Name": entry.output_name,
                "Source Filename": entry.source_filename,
                "Condition": entry.condition,
                "Temperature": entry.temperature,
                "Model": result.model if result is not None else "",
                "Number_of_Peaks": result.n_peaks if result is not None else "",
                "Export_Sheet_Name": entry.sheet_name,
                "CSV_Filename": entry.csv_filename,
                "Fit_Status": entry.fit_status,
                "Failure_Reason": entry.failure_reason,
            }
        )
    return output


def _fit_metadata(entry):
    _, spectrum, result = entry.row
    metadata = [
        ("Output Name", entry.output_name),
        ("Source Filename", spectrum.source_name),
        ("Condition", spectrum.condition),
        ("Temperature", spectrum.temperature_k),
        ("Model", result.model),
        ("Number of Peaks", result.n_peaks),
        ("R2", result.r_squared),
        ("Adjusted R2", result.adjusted_r_squared),
        ("RMSE", result.rmse),
        ("AICc", result.aicc),
        ("BIC", result.bic),
    ]
    for peak in result.peaks:
        prefix = f"Peak_{peak.peak_index}"
        metadata.extend(
            [
                (f"{prefix}_Energy_eV", peak.center_ev),
                (f"{prefix}_Wavelength_nm", peak.center_nm),
                (f"{prefix}_FWHM_meV", peak.fwhm_mev),
                (f"{prefix}_Area", peak.area),
            ]
        )
    return metadata


def _style_header(row):
    fill = PatternFill("solid", fgColor="1F4E78")
    for cell in row:
        cell.font = Font(color="FFFFFF", bold=True)
        cell.fill = fill


def _write_individual_excel(path, entries):
    index_columns = [
        "Output Name",
        "Source Filename",
        "Condition",
        "Temperature",
        "Model",
        "Number_of_Peaks",
        "Export_Sheet_Name",
        "CSV_Filename",
        "Fit_Status",
        "Failure_Reason",
    ]
    with pd.ExcelWriter(path, engine="openpyxl") as writer:
        pd.DataFrame(_index_rows(entries), columns=index_columns).to_excel(
            writer, sheet_name="Index", index=False
        )
        index_sheet = writer.sheets["Index"]
        _style_header(index_sheet[1])
        index_sheet.freeze_panes = "A2"
        index_sheet.auto_filter.ref = index_sheet.dimensions
        index_sheet.sheet_view.showGridLines = False
        index_widths = [28, 28, 20, 14, 20, 18, 31, 28, 14, 48]
        for column_index, width in enumerate(index_widths, 1):
            index_sheet.column_dimensions[get_column_letter(column_index)].width = width

        for entry in entries:
            if entry.row is None:
                continue
            metadata = _fit_metadata(entry)
            metadata_frame = pd.DataFrame(metadata, columns=["Metadata_Field", "Value"])
            metadata_frame.to_excel(writer, sheet_name=entry.sheet_name, index=False)
            curve_frame = fit_curve_dataframe(entry.row[2])
            curve_startrow = len(metadata_frame) + 2
            curve_frame.to_excel(
                writer,
                sheet_name=entry.sheet_name,
                startrow=curve_startrow,
                index=False,
            )
            worksheet = writer.sheets[entry.sheet_name]
            _style_header(worksheet[1])
            _style_header(worksheet[curve_startrow + 1])
            worksheet.freeze_panes = f"A{curve_startrow + 2}"
            last_column = worksheet.cell(curve_startrow + 1, curve_frame.shape[1]).column_letter
            worksheet.auto_filter.ref = (
                f"A{curve_startrow + 1}:{last_column}{curve_startrow + 1 + len(curve_frame)}"
            )
            worksheet.sheet_view.showGridLines = False
            worksheet.column_dimensions["A"].width = 28
            worksheet.column_dimensions["B"].width = 24
            for column_index in range(3, curve_frame.shape[1] + 1):
                worksheet.column_dimensions[get_column_letter(column_index)].width = 20


def _collect_summary_rows(rows, tempfits):
    peak_rows = []
    for label, spectrum, result in rows:
        for peak in result.peaks:
            peak_rows.append(
                {
                    "Label": label,
                    "Condition": spectrum.condition,
                    "Sample ID": spectrum.sample_id,
                    "Temperature_K": spectrum.temperature_k,
                    "Model": result.model,
                    "N peaks": result.n_peaks,
                    "Peak": peak.peak_index,
                    "Center_eV": peak.center_ev,
                    "Center_nm": peak.center_nm,
                    "FWHM_meV": peak.fwhm_mev,
                    "Height": peak.height,
                    "Area": peak.area,
                    "Area_fraction": peak.area_fraction,
                    "R2": result.r_squared,
                    "Adjusted_R2": result.adjusted_r_squared,
                    "RMSE": result.rmse,
                    "AICc": result.aicc,
                    "BIC": result.bic,
                    "Warnings": "; ".join(result.warnings),
                }
            )

    temp_rows = []
    for label, group in tempfits.items():
        for kind, result in group.items():
            for name, value in result.parameters.items():
                low, high = result.ci95[name]
                temp_rows.append(
                    {
                        "Label": label,
                        "Analysis": kind,
                        "Model": result.model,
                        "Parameter": name,
                        "Value": value,
                        "SE": result.errors[name],
                        "CI95_low": low,
                        "CI95_high": high,
                        "R2": result.r_squared,
                        "Adjusted_R2": result.adjusted_r_squared,
                        "RMSE": result.rmse,
                        "AICc": result.aicc,
                        "BIC": result.bic,
                        "Warnings": "; ".join(result.warnings),
                    }
                )
    return peak_rows, temp_rows


def _write_legacy_summary(path, rows, tempfits, peak_rows, temp_rows):
    metadata_rows = []
    curve_sheets = []
    used_sheet_names = {"peak_results", "temperature_fits", "spectrum_metadata"}
    for label, spectrum, result in rows:
        for name, value in spectrum.metadata.items():
            metadata_rows.append(
                {"Label": label, "Source": spectrum.source_name, "Key": name, "Value": value}
            )
        key = f"{label}_{spectrum.temperature_k:g}K"
        fit_sheet = unique_excel_sheet_name(f"Fit_{key}", used_sheet_names)
        residual_sheet = unique_excel_sheet_name(f"Res_{key}", used_sheet_names)
        curves = build_fit_curve_data(result)
        curve_data = {
            "Energy_eV": curves.photon_energy_ev,
            "Raw": curves.raw_intensity,
            "Total_fit": curves.total_fit,
            "Baseline": np.asarray(result.baseline, dtype=float),
        }
        for index, component in enumerate(curves.components, 1):
            curve_data[f"Peak_{index}"] = component
        curve_sheets.append(
            (
                fit_sheet,
                pd.DataFrame(curve_data),
                residual_sheet,
                pd.DataFrame({"Energy_eV": curves.photon_energy_ev, "Residual": curves.residual}),
            )
        )

    with pd.ExcelWriter(path, engine="openpyxl") as writer:
        pd.DataFrame(peak_rows).to_excel(writer, sheet_name="Peak_Results", index=False)
        pd.DataFrame(temp_rows).to_excel(writer, sheet_name="Temperature_Fits", index=False)
        pd.DataFrame(metadata_rows, columns=["Label", "Source", "Key", "Value"]).to_excel(
            writer, sheet_name="Spectrum_Metadata", index=False
        )
        for fit_sheet, fit_frame, residual_sheet, residual_frame in curve_sheets:
            fit_frame.to_excel(writer, sheet_name=fit_sheet, index=False)
            residual_frame.to_excel(writer, sheet_name=residual_sheet, index=False)


def export_all(outdir, rows, tempfits, figures, *, records=None, options=None):
    """Export summaries, exact individual curves, metadata, and figures."""
    options = _coerce_options(options)
    out = Path(outdir)
    out.mkdir(parents=True, exist_ok=True)
    rows = list(rows)
    entries = _build_entries(rows, records)

    used_csv_names = set()
    used_sheet_names = {"index"}
    for entry in entries:
        if entry.row is None:
            continue
        if options.individual_csv:
            entry.csv_filename = unique_csv_filename(entry.output_name, used_csv_names)
        if options.individual_excel:
            entry.sheet_name = unique_excel_sheet_name(entry.output_name, used_sheet_names)

    peak_rows, temp_rows = _collect_summary_rows(rows, tempfits)
    if options.summary_excel:
        _write_legacy_summary(out / "PL_batch_results.xlsx", rows, tempfits, peak_rows, temp_rows)

    pd.DataFrame(peak_rows).to_csv(
        out / "peak_results.csv", index=False, encoding="utf-8-sig"
    )
    pd.DataFrame(temp_rows).to_csv(
        out / "temperature_fit_results.csv", index=False, encoding="utf-8-sig"
    )
    payload = {
        "spectra": [
            {
                "label": label,
                "spectrum": {
                    "condition": spectrum.condition,
                    "sample_id": spectrum.sample_id,
                    "temperature_k": spectrum.temperature_k,
                    "source_name": spectrum.source_name,
                    "metadata": spectrum.metadata,
                },
                "fit": result_to_dict(result),
            }
            for label, spectrum, result in rows
        ],
        "temperature_fits": {
            label: {name: result_to_dict(value) for name, value in group.items()}
            for label, group in tempfits.items()
        },
    }
    (out / "analysis_results.json").write_text(
        json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8"
    )

    csv_count = 0
    if options.individual_csv:
        csv_directory = out / "Individual_Fit_Data"
        csv_directory.mkdir(parents=True, exist_ok=True)
        for entry in entries:
            if entry.row is None:
                continue
            fit_curve_dataframe(entry.row[2]).to_csv(
                csv_directory / entry.csv_filename,
                index=False,
                encoding="utf-8-sig",
                float_format="%.17g",
            )
            csv_count += 1
        (csv_directory / "Index.json").write_text(
            json.dumps(_index_rows(entries), ensure_ascii=False, indent=2), encoding="utf-8"
        )

    if options.individual_excel:
        _write_individual_excel(out / "Individual_Fitting_Data.xlsx", entries)

    for name, figure in figures.items():
        if options.figures_png:
            figure.savefig(out / f"{name}.png", dpi=300)
        if options.figures_pdf:
            figure.savefig(out / f"{name}.pdf")

    return {
        "successful_curve_exports": sum(entry.row is not None for entry in entries),
        "csv_files": csv_count,
        "index_rows": len(entries),
    }

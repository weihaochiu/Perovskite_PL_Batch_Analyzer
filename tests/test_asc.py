import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import numpy as np
import pandas as pd

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication, QMessageBox

from app import MainWindow, SPECTRUM_FILE_FILTER, SUPPORTED_SPECTRUM_EXTENSIONS
from export_manager import ExportOptions, export_all
from pl_core import fit_spectrum, numeric_columns, prepare_spectrum, read_asc, read_table


METADATA = {
    "Date and Time": "Fri Aug 14 15:23:45 2026",
    "Software Version": "1.2.3",
    "Temperature (C)": "25",
    "Model": "Example Spectrometer",
    "Data Type": "Counts",
    "Acquisition Mode": "Single Scan",
    "Trigger Mode": "Internal",
    "Exposure Time (secs)": "0.5",
    "Number of Accumulations": "3",
    "Wavelength (nm)": "800",
    "Grating Groove Density (l/mm)": "600",
}


def write_asc(path: Path, wavelengths, intensities, *, bom=False, separator="\t"):
    rows = [f"{x:.5f}{separator}{y:.8f}   " for x, y in zip(wavelengths, intensities)]
    rows.extend(["", *(f"{key}: {value}" for key, value in METADATA.items()), "123\t456"])
    content = "\r\n".join(rows) + "\r\n"
    path.write_text(content, encoding="utf-8-sig" if bom else "ascii", newline="")


def anti_1_arrays():
    """Controlled synthetic fixture matching the documented ASC size and endpoints."""
    wavelength = np.linspace(699.97467, 897.23474, 1024)
    energy = 1239.841984 / wavelength
    intensity = 7300 + 25000 * np.exp(-4 * np.log(2) * ((energy - 1.55) / 0.07) ** 2)
    intensity[0] = 7295
    intensity[-1] = 7368
    return wavelength, intensity


class TestAscImport(unittest.TestCase):
    def test_reads_anti_1_shape_endpoints_and_metadata(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "Anti-1.asc"
            wavelength, intensity = anti_1_arrays()
            write_asc(path, wavelength, intensity)

            frame = read_table(path)

        self.assertEqual(len(frame), 1024)
        self.assertAlmostEqual(frame.iloc[0]["Wavelength_nm"], 699.97467, places=5)
        self.assertAlmostEqual(frame.iloc[0]["PL_Intensity"], 7295, places=5)
        self.assertAlmostEqual(frame.iloc[-1]["Wavelength_nm"], 897.23474, places=5)
        self.assertAlmostEqual(frame.iloc[-1]["PL_Intensity"], 7368, places=5)
        self.assertEqual(frame.attrs["metadata"], METADATA)
        self.assertEqual(frame.attrs["source_format"], "ASC")

    def test_crlf_bom_blank_lines_whitespace_and_uppercase_extension(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "spacing.ASC"
            wavelength = np.linspace(700, 711, 12)
            intensity = np.arange(12, dtype=float)
            write_asc(path, wavelength, intensity, bom=True, separator="    ")

            frame = read_table(path)

        np.testing.assert_allclose(frame["Wavelength_nm"], wavelength)
        np.testing.assert_allclose(frame["PL_Intensity"], intensity)

    def test_non_fixed_point_count(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "seventeen.asc"
            write_asc(path, np.linspace(700, 716, 17), np.linspace(1, 17, 17))
            frame = read_asc(path)
        self.assertEqual(len(frame), 17)

    def test_reverse_wavelength_uses_existing_energy_sort_and_keeps_pairs(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "reverse.asc"
            wavelength = np.linspace(720, 700, 21)
            intensity = wavelength * 2
            write_asc(path, wavelength, intensity)
            frame = read_table(path)
            spectrum = prepare_spectrum(frame, "Wavelength_nm", "PL_Intensity")

        self.assertTrue(np.all(np.diff(spectrum.photon_energy_ev) > 0))
        np.testing.assert_allclose(spectrum.intensity_wavelength, spectrum.wavelength_nm * 2)

    def test_duplicate_wavelength_uses_existing_mean_cleanup(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "duplicate.asc"
            wavelength = np.r_[np.linspace(700, 711, 12), 705]
            intensity = np.r_[np.linspace(10, 21, 12), 99]
            write_asc(path, wavelength, intensity)
            frame = read_table(path)
            spectrum = prepare_spectrum(frame, "Wavelength_nm", "PL_Intensity")

        duplicate_index = np.flatnonzero(np.isclose(spectrum.wavelength_nm, 705))[0]
        self.assertAlmostEqual(spectrum.intensity_wavelength[duplicate_index], (15 + 99) / 2)

    def test_invalid_asc_files_raise_clear_errors(self):
        invalid_cases = {
            "empty.asc": "",
            "one-column.asc": "\r\n".join(str(value) for value in range(12)),
            "non-numeric.asc": "alpha\tbeta\r\ngamma\tdelta\r\n",
            "metadata-numbers.asc": "Model: 123\r\n456\t789\r\n457\t790\r\n",
            "not-finite.asc": "\r\n".join("NaN\tInf" for _ in range(12)),
            "too-short.asc": "\r\n".join(f"{700 + value}\t{value}" for value in range(11)),
        }
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            for filename, content in invalid_cases.items():
                with self.subTest(filename=filename):
                    path = root / filename
                    path.write_text(content, encoding="ascii")
                    with self.assertRaisesRegex(ValueError, "找不到|不足"):
                        read_table(path)

    def test_mixed_csv_and_asc_follow_the_same_preparation_flow(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            asc_path = root / "Anti-1.ASC"
            csv_path = root / "Existing_300K.csv"
            wavelength = np.linspace(700, 730, 31)
            intensity = np.linspace(10, 40, 31)
            write_asc(asc_path, wavelength, intensity)
            pd.DataFrame({"wl": wavelength, "pl": intensity}).to_csv(csv_path, index=False)

            spectra = []
            for path in (asc_path, csv_path):
                frame = read_table(path)
                columns = numeric_columns(frame)
                spectra.append(prepare_spectrum(frame, columns[0], columns[1], sample_id=path.stem))

        self.assertEqual([s.sample_id for s in spectra], ["Anti-1", "Existing_300K"])
        self.assertTrue(all(len(s.wavelength_nm) == 31 for s in spectra))
        self.assertIn(".asc", SUPPORTED_SPECTRUM_EXTENSIONS)
        self.assertIn("ASC files (*.asc)", SPECTRUM_FILE_FILTER)

    def test_gui_batch_import_skips_bad_asc_and_keeps_mixed_valid_files(self):
        application = QApplication.instance() or QApplication([])
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            asc_path = root / "Anti-1.ASC"
            bad_path = root / "Broken.asc"
            csv_path = root / "Existing_300K.csv"
            wavelength = np.linspace(700, 730, 31)
            intensity = np.linspace(10, 40, 31)
            write_asc(asc_path, wavelength, intensity)
            bad_path.write_text("not spectrum data", encoding="ascii")
            pd.DataFrame({"wl": wavelength, "pl": intensity}).to_csv(csv_path, index=False)
            window = MainWindow()

            with patch.object(QMessageBox, "warning") as warning:
                window.add_paths([bad_path, asc_path, csv_path])

            self.assertEqual([record["code"] for record in window.records], ["Anti-1", "Existing_300K"])
            self.assertEqual(window.records[0]["sample_id"], "Anti-1")
            warning.assert_called_once()
            self.assertIn("Broken.asc", warning.call_args.args[2])
            self.assertIn("原因", warning.call_args.args[2])
            window.close()
        application.processEvents()

    def test_asc_runs_gaussian_fit_and_exports_metadata(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            path = root / "Anti-1.asc"
            wavelength, intensity = anti_1_arrays()
            write_asc(path, wavelength, intensity)
            frame = read_table(path)
            spectrum = prepare_spectrum(
                frame,
                "Wavelength_nm",
                "PL_Intensity",
                sample_id=path.stem,
                source_name=path.name,
            )
            result = fit_spectrum(
                spectrum,
                model="Gaussian",
                n_peaks=1,
                baseline_mode="Constant",
                use_jacobian=False,
            )
            output = root / "output"
            export_all(
                output,
                [(path.stem, spectrum, result)],
                {},
                {},
                options=ExportOptions(timestamped_folder=False),
            )
            exported_metadata = pd.read_excel(output / "PL_batch_results.xlsx", sheet_name="Spectrum_Metadata")
            payload = json.loads((output / "analysis_results.json").read_text(encoding="utf-8"))

        self.assertAlmostEqual(result.peaks[0].center_ev, 1.55, places=3)
        self.assertEqual(dict(zip(exported_metadata["Key"], exported_metadata["Value"].astype(str)))["Model"], METADATA["Model"])
        self.assertEqual(payload["spectra"][0]["spectrum"]["metadata"]["Data Type"], "Counts")


if __name__ == "__main__":
    unittest.main()

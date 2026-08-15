import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import matplotlib

matplotlib.use("Agg")

import numpy as np
import pandas as pd
from PySide6.QtWidgets import QApplication, QFileDialog, QMessageBox

from app import MainWindow
from pl_core import PLSpectrum, PeakResult, SpectrumFitResult
from plotting import (
    categorical_parameter_figure,
    group_condition_values,
    natural_sort_key,
    normalize_condition,
    select_dominant_peak,
)


def make_peak(index=1, *, center=1.55, fwhm=70.0, height=100.0, area=10.0):
    return PeakResult(
        peak_index=index,
        center_ev=center,
        center_nm=1239.841984 / center,
        fwhm_ev=fwhm / 1000.0,
        fwhm_mev=fwhm,
        height=height,
        area=area,
        area_fraction=1.0,
        parameters={},
        errors={},
    )


def make_row(label, condition, peaks, *, sample_id=None, source_name=None):
    energy = np.linspace(1.4, 1.8, 8)
    wavelength = 1239.841984 / energy
    intensity = np.linspace(10.0, 20.0, len(energy))
    spectrum = PLSpectrum(
        wavelength_nm=wavelength,
        photon_energy_ev=energy,
        intensity_wavelength=intensity,
        intensity_energy=intensity.copy(),
        temperature_k=300.0,
        condition=condition,
        sample_id=condition if sample_id is None else sample_id,
        source_name=source_name or f"{label}.asc",
        metadata={},
    )
    result = SpectrumFitResult(
        temperature_k=300.0,
        model="Gaussian",
        n_peaks=len(peaks),
        peaks=list(peaks),
        x_ev=energy,
        y_raw=intensity,
        y_fit=intensity * 0.98,
        components=[intensity * (0.8 / len(peaks)) for _ in peaks],
        baseline=np.full_like(energy, 2.0),
        residual=intensity * 0.02,
        r_squared=0.99,
        adjusted_r_squared=0.98,
        rmse=0.1,
        reduced_chi2=0.01,
        aic=1.0,
        aicc=2.0,
        bic=3.0,
        warnings=[],
    )
    return label, spectrum, result


class TestConditionHelpers(unittest.TestCase):
    def test_terminal_replicates_are_normalized_without_truncating_middle_digits(self):
        self.assertEqual([normalize_condition(f"Anti-{index}") for index in range(1, 5)], ["Anti"] * 4)
        self.assertEqual([normalize_condition(f"C1-{index}") for index in range(1, 5)], ["C1"] * 4)
        self.assertEqual(normalize_condition("Batch2_stage"), "Batch2_stage")
        self.assertEqual(normalize_condition("C1_sample-1"), "C1_sample")
        self.assertEqual(normalize_condition("C1_sample-2"), "C1_sample")

    def test_blank_condition_falls_back_in_the_required_order(self):
        self.assertEqual(normalize_condition("  ", "Sample-2", "Code-3", "File-4.asc"), "Sample")
        self.assertEqual(normalize_condition("", "", "Code-3", "File-4.asc"), "Code")
        self.assertEqual(normalize_condition("", "", "", "File-4.asc"), "File")

    def test_natural_sort_orders_digit_runs_numerically(self):
        names = ["C10", "C2", "Anti", "C5", "C1", "C4", "C3"]
        self.assertEqual(sorted(names, key=natural_sort_key), ["Anti", "C1", "C2", "C3", "C4", "C5", "C10"])

    def test_case_insensitive_grouping_preserves_first_display_name_and_each_replicate(self):
        rows = [
            make_row("a", " Anti-1 ", [make_peak(height=10)]),
            make_row("b", "anti-2", [make_peak(height=11)]),
            make_row("c", "ANTI-3", [make_peak(height=12)]),
            make_row("d", "Anti-4", [make_peak(height=13)]),
        ]
        groups, warnings = group_condition_values(rows, lambda peak: peak.height, "height")
        self.assertEqual(warnings, [])
        self.assertEqual(len(groups), 1)
        self.assertEqual(groups[0].name, "Anti")
        self.assertEqual(groups[0].values, (10.0, 11.0, 12.0, 13.0))
        self.assertEqual(groups[0].labels, ("a", "b", "c", "d"))
        self.assertEqual([row[1].condition for row in rows], [" Anti-1 ", "anti-2", "ANTI-3", "Anti-4"])

    def test_dominant_peak_uses_area_then_height_fallback(self):
        sole = make_peak(center=1.6, area=np.nan, height=4)
        self.assertIs(select_dominant_peak(type("Result", (), {"peaks": [sole]})()), sole)
        low_area = make_peak(1, center=1.45, area=4, height=1000)
        dominant = make_peak(2, center=1.65, area=40, height=20)
        self.assertIs(select_dominant_peak(type("Result", (), {"peaks": [low_area, dominant]})()), dominant)
        invalid_area = make_peak(1, area=np.nan, height=10)
        tallest = make_peak(2, area=np.inf, height=30)
        self.assertIs(select_dominant_peak(type("Result", (), {"peaks": [invalid_area, tallest]})()), tallest)
        valid_area = make_peak(1, area=100, height=10)
        invalid_but_tallest = make_peak(2, area=np.nan, height=50)
        self.assertIs(
            select_dominant_peak(type("Result", (), {"peaks": [valid_area, invalid_but_tallest]})()),
            invalid_but_tallest,
        )

    def test_nonfinite_values_are_skipped_without_losing_valid_replicates(self):
        rows = [
            make_row("valid", "C1-1", [make_peak(height=8)]),
            make_row("nan", "C1-2", [make_peak(height=np.nan)]),
            make_row("plus-inf", "C1-3", [make_peak(height=np.inf)]),
            make_row("minus-inf", "C1-4", [make_peak(height=-np.inf)]),
        ]
        groups, warnings = group_condition_values(rows, lambda peak: peak.height, "height")
        self.assertEqual(groups[0].values, (8.0,))
        self.assertEqual(len(warnings), 3)
        figure, all_invalid_warnings = categorical_parameter_figure(
            rows[1:], lambda peak: peak.height, "Peak intensity (a.u.)", "Peak intensity vs condition"
        )
        self.assertIsNone(figure)
        self.assertTrue(any("No finite data" in warning for warning in all_invalid_warnings))


class TestCategoricalFigure(unittest.TestCase):
    def test_replicates_share_exact_x_coordinate_and_mean_sd_use_ddof_one(self):
        rows = [
            make_row("c1-1", "C1-1", [make_peak(height=10)]),
            make_row("c1-2", "C1-2", [make_peak(height=14)]),
            make_row("c2-1", "C2-1", [make_peak(height=20)]),
        ]
        figure, warnings = categorical_parameter_figure(
            rows, lambda peak: peak.height, "Peak intensity (a.u.)", "Peak intensity vs condition"
        )
        self.assertEqual(warnings, [])
        axis = figure.axes[0]
        replicate_offsets = np.asarray(axis.collections[0].get_offsets(), dtype=float)
        np.testing.assert_allclose(replicate_offsets[:, 0], [0, 0, 1])
        np.testing.assert_allclose(replicate_offsets[:, 1], [10, 14, 20])
        mean_offsets = np.asarray(axis.collections[1].get_offsets(), dtype=float)
        np.testing.assert_allclose(mean_offsets[:, 1], [12, 20])
        error_collections = [collection for collection in axis.collections if hasattr(collection, "get_segments")]
        self.assertEqual(len(error_collections), 1)
        segments = error_collections[0].get_segments()
        self.assertEqual(len(segments), 1)
        expected_sd = np.std([10.0, 14.0], ddof=1)
        np.testing.assert_allclose(segments[0][:, 1], [12 - expected_sd, 12 + expected_sd])
        figure.clear()

    def test_single_replicate_has_mean_but_no_sd_errorbar(self):
        figure, warnings = categorical_parameter_figure(
            [make_row("only", "C1-1", [make_peak(height=7)])],
            lambda peak: peak.height,
            "Peak intensity (a.u.)",
            "Peak intensity vs condition",
        )
        self.assertEqual(warnings, [])
        axis = figure.axes[0]
        self.assertEqual(len([collection for collection in axis.collections if hasattr(collection, "get_segments")]), 0)
        self.assertEqual(axis.get_legend_handles_labels()[1], ["Individual replicate", "Mean"])
        figure.clear()

    def test_all_three_metrics_use_the_same_area_dominant_peak_and_height_for_intensity(self):
        non_dominant = make_peak(1, center=1.42, fwhm=25, height=999, area=2)
        dominant = make_peak(2, center=1.68, fwhm=83, height=57, area=40)
        rows = [make_row("multi", "C1-1", [non_dominant, dominant])]
        cases = (
            (lambda peak: peak.center_ev, 1.68),
            (lambda peak: peak.fwhm_mev, 83),
            (lambda peak: peak.height, 57),
        )
        for selector, expected in cases:
            with self.subTest(expected=expected):
                figure, warnings = categorical_parameter_figure(rows, selector, "Y", "Title")
                self.assertEqual(warnings, [])
                offsets = np.asarray(figure.axes[0].collections[0].get_offsets(), dtype=float)
                self.assertAlmostEqual(offsets[0, 1], expected)
                figure.clear()


class TestConditionPlotsInGui(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.application = QApplication.instance() or QApplication([])

    def test_tabs_lifecycle_selected_fit_and_export_include_condition_figures(self):
        rows = [
            make_row("Anti-1", "Anti-1", [make_peak(center=1.52, fwhm=65, height=90, area=12)]),
            make_row("Anti-2", "Anti-2", [make_peak(center=1.54, fwhm=68, height=95, area=13)]),
            make_row("C1-1", "C1-1", [make_peak(center=1.58, fwhm=72, height=105, area=14)]),
            make_row("C1-2", "C1-2", [make_peak(center=1.60, fwhm=75, height=110, area=15)]),
        ]
        expected_keys = {
            "peak_energy_by_condition",
            "fwhm_by_condition",
            "peak_intensity_by_condition",
        }
        expected_tabs = {
            "Peak energy by condition",
            "FWHM by condition",
            "Peak intensity by condition",
        }
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            window = MainWindow()
            window.results = rows
            for label, spectrum, _ in rows:
                record = {
                    "use": True,
                    "export": True,
                    "condition": spectrum.condition,
                    "sample_id": spectrum.sample_id,
                    "temperature": spectrum.temperature_k,
                    "direction": "Isothermal",
                    "code": label,
                    "path": str(root / f"{label}.asc"),
                    "x": "Wavelength_nm",
                    "y": "PL_Intensity",
                    "status": "OK",
                }
                window.records.append(record)
                window._add_row(record)

            window.refresh_tabs()
            self.assertTrue(expected_keys.issubset(window.figures))
            tab_names = {window.tabs.tabText(index) for index in range(window.tabs.count())}
            self.assertTrue(expected_tabs.issubset(tab_names))

            condition_figures = {key: window.figures[key] for key in expected_keys}
            window.table.selectRow(1)
            self.application.processEvents()
            for key, figure in condition_figures.items():
                self.assertIs(window.figures[key], figure)

            old_figures = dict(window.figures)
            window.refresh_tabs()
            self.application.processEvents()
            self.assertTrue(expected_keys.issubset(window.figures))
            for figure in old_figures.values():
                self.assertEqual(figure.axes, [])

            output = root / "export"
            with patch.object(QFileDialog, "getExistingDirectory", return_value=str(output)), patch.object(
                QMessageBox, "information"
            ):
                window.export()
            for key in expected_keys:
                self.assertTrue((output / f"{key}.png").is_file())
                self.assertTrue((output / f"{key}.pdf").is_file())
            peak_results = pd.read_excel(output / "PL_batch_results.xlsx", sheet_name="Peak_Results")
            self.assertEqual(peak_results["Condition"].tolist(), ["Anti-1", "Anti-2", "C1-1", "C1-2"])
            self.assertEqual(
                peak_results.columns.tolist(),
                [
                    "Label",
                    "Condition",
                    "Sample ID",
                    "Temperature_K",
                    "Model",
                    "N peaks",
                    "Peak",
                    "Center_eV",
                    "Center_nm",
                    "FWHM_meV",
                    "Height",
                    "Area",
                    "Area_fraction",
                    "R2",
                    "Adjusted_R2",
                    "RMSE",
                    "AICc",
                    "BIC",
                    "Warnings",
                ],
            )
            window.close()
        self.application.processEvents()


if __name__ == "__main__":
    unittest.main()

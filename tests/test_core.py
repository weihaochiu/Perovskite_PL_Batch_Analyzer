from pathlib import Path
import tempfile
import unittest

import numpy as np
import pandas as pd

from pl_core import fit_spectrum, fit_temperature, prepare_spectrum, read_table


def synthetic_spectrum(n_peaks=1, *, linear_baseline=False):
    wavelength = np.linspace(680.0, 920.0, 800)
    energy = 1239.841984 / wavelength
    centers = np.linspace(1.43, 1.72, n_peaks)
    intensity = np.zeros_like(energy)
    for index, center in enumerate(centers):
        height = 900.0 - index * 120.0
        intensity += height * np.exp(-4 * np.log(2) * ((energy - center) / 0.045) ** 2)
    intensity += 15.0 + (20.0 * (energy - energy.mean()) if linear_baseline else 0.0)
    frame = pd.DataFrame({"wl": wavelength, "pl": intensity})
    return prepare_spectrum(frame, "wl", "pl", temperature_k=300)


class TestCoreScientificRegression(unittest.TestCase):
    def test_peak_fit(self):
        wavelength = np.linspace(700, 850, 700)
        energy = 1239.841984 / wavelength
        intensity = 1000 * np.exp(-4 * np.log(2) * ((energy - 1.55) / 0.055) ** 2) + 10
        spectrum = prepare_spectrum(pd.DataFrame({"wl": wavelength, "pl": intensity}), "wl", "pl", temperature_k=300)
        result = fit_spectrum(spectrum, model="Gaussian", n_peaks=1, baseline_mode="Constant", use_jacobian=False)
        self.assertLess(abs(result.peaks[0].center_ev - 1.55), 0.002)
        self.assertLess(abs(result.peaks[0].fwhm_ev - 0.055), 0.003)

    def test_temperature_linear(self):
        temperature = np.array([100, 150, 200, 250, 300.0])
        values = 1.6 + 2e-4 * temperature
        result = fit_temperature(temperature, values, "Peak energy", "Linear")
        self.assertLess(abs(result.parameters["slope_eV_per_K"] - 2e-4), 1e-8)

    def test_manual_models_peak_counts_baselines_and_jacobian_modes(self):
        one_peak = synthetic_spectrum()
        for model in ["Gaussian", "Lorentzian", "Pseudo-Voigt", "Voigt"]:
            with self.subTest(model=model):
                result = fit_spectrum(one_peak, model=model, n_peaks=1, baseline_mode="Constant", use_jacobian=False)
                self.assertEqual(result.model, model)
                self.assertTrue(np.isfinite(result.y_fit).all())

        for n_peaks in [1, 2, 3]:
            with self.subTest(n_peaks=n_peaks):
                result = fit_spectrum(synthetic_spectrum(n_peaks), model="Gaussian", n_peaks=n_peaks, baseline_mode="Constant", use_jacobian=False)
                self.assertEqual(result.n_peaks, n_peaks)
                self.assertEqual(len(result.components), n_peaks)

        baseline_cases = [("Constant", False), ("Linear", True), ("None", False)]
        for baseline_mode, linear in baseline_cases:
            with self.subTest(baseline_mode=baseline_mode):
                spectrum = synthetic_spectrum(linear_baseline=linear)
                if baseline_mode == "None":
                    spectrum.intensity_wavelength = spectrum.intensity_wavelength.copy() - 15.0
                result = fit_spectrum(spectrum, model="Gaussian", n_peaks=1, baseline_mode=baseline_mode, use_jacobian=False)
                self.assertEqual(result.fit_settings.baseline_mode, baseline_mode)

        for jacobian in [False, True]:
            with self.subTest(jacobian=jacobian):
                result = fit_spectrum(one_peak, model="Gaussian", n_peaks=1, baseline_mode="Constant", use_jacobian=jacobian)
                self.assertEqual(result.fit_settings.jacobian_corrected, jacobian)

    def test_csv_and_excel_import_share_table_reader(self):
        frame = pd.DataFrame({"Wavelength_nm": [700.0, 701.0], "PL_Intensity": [10.0, 11.0]})
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            csv_path = root / "sample.csv"
            excel_path = root / "sample.xlsx"
            frame.to_csv(csv_path, index=False)
            frame.to_excel(excel_path, index=False)
            pd.testing.assert_frame_equal(read_table(csv_path), frame, check_dtype=False)
            pd.testing.assert_frame_equal(read_table(excel_path), frame, check_dtype=False)


if __name__ == "__main__":
    unittest.main()

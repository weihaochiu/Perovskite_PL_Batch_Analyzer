# Perovskite Steady-State PL Batch Analyzer

PySide6 desktop application for multi-sample room-temperature and temperature-dependent steady-state PL analysis.

## Implemented analyses

- Gaussian, Lorentzian, pseudo-Voigt and Voigt single-/multi-peak fitting
- Automatic 1–2 peak model selection using BIC with a simplicity preference
- Peak energy, FWHM, integrated area, component fraction, residual, R², adjusted R², RMSE, reduced χ², AIC/AICc/BIC
- Temperature fits: linear, Varshni, Bose–Einstein, acoustic/LO/full phonon linewidth, one-/two-channel Arrhenius PL quenching
- Multi-sample room-temperature overlays and comparisons
- Multi-sample temperature series, contour maps and parameter comparison plots
- CSV/XLS/XLSX/TXT/DAT/ASC input, `.plproj` projects, summary and individual-curve Excel/CSV/JSON/300 dpi PNG/vector PDF export
- Wavelength-to-energy Jacobian correction

## Windows quick start

1. Install 64-bit Python 3.11 and select **Add Python to PATH**.
2. Extract the ZIP.
3. For the first installation, double-click `setup_windows.bat`. It creates the repository-local `.venv` and installs the runtime requirements.
4. After setup succeeds, double-click `run_windows.bat`.
5. For normal use after the first installation, only run `run_windows.bat`.
6. Add spectra. Filenames containing `80K`, `300K`, etc. are parsed automatically.
7. Edit Condition, Sample ID and Temperature in the table as needed.
8. Click **Batch fit**, inspect plots, then **Export**.

Batch fitting runs one spectrum at a time on a background thread. The progress panel reports the current file, completed/total count, percentage, last-file duration, and estimated time remaining. **Cancel Batch Fit** stops at the next file boundary and keeps every completed result. A durable JSON Lines checkpoint and a phased timing log are written after each attempted file under the application's local data `batch_runs` directory; the status bar reports completion while the checkpoint path is also available in the batch summary.

Cancellation cannot interrupt a `scipy.optimize.curve_fit` call already in progress. It takes effect immediately after that file succeeds or fails, which avoids leaving a partially constructed scientific result.

The daily launcher uses only `.venv\Scripts\python.exe`. It never falls back to system Python and does not reinstall packages at every startup. Run `setup_windows.bat` again only when installing for the first time or repairing the environment.

## Windows setup troubleshooting

- **Python 3.11 not found:** Install 64-bit Python 3.11, enable **Add Python to PATH**, close the old Command Prompt window, and run `setup_windows.bat` again. The setup rejects incompatible Python versions.
- **`.venv` does not exist:** Run `setup_windows.bat` before `run_windows.bat`.
- **`.venv` is damaged or uses the wrong Python version:** The setup does not delete or overwrite an existing environment. Move or remove `.venv` manually, then run `setup_windows.bat` to create a clean Python 3.11 environment.
- **Requirements installation fails:** Read the pip error shown above the setup message, check the network connection, and rerun `setup_windows.bat`. The window remains open so the original error and exit code can be inspected.

## Input examples

One spectrum per file:

```csv
Wavelength_nm,PL_Intensity
700,10
701,12
...
```

Recommended filenames: `AS_80K.csv`, `AS_100K.csv`, `CP20_80K.csv`.

ASC files may contain a leading whitespace-delimited wavelength/intensity block followed by blank lines and `Key: Value` instrument metadata. The metadata is preserved in JSON output and the Excel `Spectrum_Metadata` worksheet.

## Origin / external plotting export

The export panel enables individual fitting curve CSV and Excel output by default. Each export normally creates a new `PL_Export_YYYYMMDD_HHMMSS/` dataset under the selected folder, so files from an earlier run cannot be mistaken for current results. The app never clears the user-selected folder. If timestamped folders are disabled, it removes only files named in its own previous `Export_Manifest.json`; unrelated user files are preserved.

Every selected successful spectrum produces one UTF-8-with-BOM CSV in `Individual_Fit_Data/`, named from its current **Output Name**, plus one worksheet in `Individual_Fitting_Data.xlsx`. `record_id` is the immutable internal identity that joins the GUI record and fitted result; **Output Name** is editable display/export naming. Identical source basenames, changed Output Names, Windows-invalid characters, reserved device names, case-insensitive collisions, and Excel's 31-character worksheet limit therefore cannot change result identity or overwrite another spectrum.

Each curve table contains `Photon_Energy_eV`, `Wavelength_nm`, `Fit_Input_Intensity`, optional `Baseline`, dynamically numbered pure components such as `Peak_1`, compatibility display curves such as `Peak_1_With_Baseline`, `Total_Fit`, and `Residual`. All numerical arrays come directly from the same saved `build_fit_curve_data()` result used by the selected-fit GUI plot; export does not refit.

- `Peak_n` is the pure fitted peak component.
- `Baseline` is an independent component.
- `Peak_n_With_Baseline = Peak_n + Baseline` reconstructs the older component display style.
- `Total_Fit = Baseline + sum(Peak_n)` when a baseline is present.
- `Residual = Fit_Input_Intensity - Total_Fit`.

`Fit_Input_Intensity` means the actual Y array passed to fitting. With Jacobian correction enabled it is an energy-domain, Jacobian-corrected spectrum and is not the original wavelength-domain detector count. The individual workbook metadata and `Individual_Fit_Data/Index.json` record the `record_id`, full source path, sample/condition/temperature, selected and requested models, peak count, baseline mode, Jacobian state, intensity domain, fit range, instrument FWHM, fit statistics, and peak metadata.

The **Export** checkbox controls all spectrum-level outputs consistently: individual CSV, individual Excel spectrum sheets, peak results, spectrum metadata, and `analysis_results.json` spectra. Temperature fits remain the aggregate result calculated from the complete `Use = True` batch and are exported without being recalculated when individual Export boxes change.

`PL_batch_results.xlsx` is a summary workbook containing `Peak_Results`, `Temperature_Fits`, and `Spectrum_Metadata`. Point-by-point curves belong in `Individual_Fitting_Data.xlsx`; legacy `Fit_*` and `Res_*` summary-workbook sheets are available only when **Legacy combined Excel curve sheets** is enabled. Failed selected fits remain visible in the individual `Index` with their failure reason but never receive an empty or fabricated curve file.

## Scientific cautions

- Final fitting uses unsmoothed data; smoothing is used only for initial peak detection.
- A lower BIC does not itself prove a physical second emissive state.
- Arrhenius output is labeled PL-quenching activation energy; it is not automatically a trap depth or exciton binding energy.
- Full phonon and two-channel Arrhenius models display warnings when the number or span of temperature points is insufficient.

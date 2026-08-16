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

The export panel enables individual fitting curve CSV and Excel output by default. Every successful spectrum produces one UTF-8-with-BOM CSV in `Individual_Fit_Data/`, named from its full **Output Name**, plus one worksheet in `Individual_Fitting_Data.xlsx`. Windows-invalid filename characters, Excel's 31-character worksheet limit, and duplicate names are handled only in the exported filename or sheet name; the original Output Name remains unchanged in the workbook and index metadata.

Each curve table contains the complete point-by-point `Photon_Energy_eV`, `Wavelength_nm`, `Raw_Intensity`, optional `Baseline`, dynamically numbered `Peak_1`, `Peak_2`, ... component contributions, `Total_Fit`, and `Residual`. These are the same saved numerical arrays used by the selected-fit GUI plot; they are not re-fitted or log-transformed during export. Residual is defined as `Raw_Intensity - Total_Fit`.

The workbook's first `Index` sheet maps every requested record to its Output Name, source file, condition, temperature, model, peak count, exported worksheet, CSV filename, and fit status. Failed fits remain visible in the index with their available failure reason, but do not receive an empty or fabricated curve file. This layout supports direct replotting in Origin, Excel, MATLAB, and other numerical software.

## Scientific cautions

- Final fitting uses unsmoothed data; smoothing is used only for initial peak detection.
- A lower BIC does not itself prove a physical second emissive state.
- Arrhenius output is labeled PL-quenching activation energy; it is not automatically a trap depth or exciton binding energy.
- Full phonon and two-channel Arrhenius models display warnings when the number or span of temperature points is insufficient.

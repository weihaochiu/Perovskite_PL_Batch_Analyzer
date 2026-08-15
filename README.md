# Perovskite Steady-State PL Batch Analyzer

PySide6 desktop application for multi-sample room-temperature and temperature-dependent steady-state PL analysis.

## Implemented analyses

- Gaussian, Lorentzian, pseudo-Voigt and Voigt single-/multi-peak fitting
- Automatic 1–2 peak model selection using BIC with a simplicity preference
- Peak energy, FWHM, integrated area, component fraction, residual, R², adjusted R², RMSE, reduced χ², AIC/AICc/BIC
- Temperature fits: linear, Varshni, Bose–Einstein, acoustic/LO/full phonon linewidth, one-/two-channel Arrhenius PL quenching
- Multi-sample room-temperature overlays and comparisons
- Multi-sample temperature series, contour maps and parameter comparison plots
- CSV/XLS/XLSX/TXT/DAT/ASC input, `.plproj` projects, Excel/CSV/JSON/300 dpi PNG/vector PDF export
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

## Scientific cautions

- Final fitting uses unsmoothed data; smoothing is used only for initial peak detection.
- A lower BIC does not itself prove a physical second emissive state.
- Arrhenius output is labeled PL-quenching activation energy; it is not automatically a trap depth or exciton binding energy.
- Full phonon and two-channel Arrhenius models display warnings when the number or span of temperature points is insufficient.

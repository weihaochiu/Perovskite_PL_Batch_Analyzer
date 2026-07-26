# Perovskite Steady-State PL Batch Analyzer

PySide6 desktop application for multi-sample room-temperature and temperature-dependent steady-state PL analysis.

## Implemented analyses

- Gaussian, Lorentzian, pseudo-Voigt and Voigt single-/multi-peak fitting
- Automatic 1–2 peak model selection using BIC with a simplicity preference
- Peak energy, FWHM, integrated area, component fraction, residual, R², adjusted R², RMSE, reduced χ², AIC/AICc/BIC
- Temperature fits: linear, Varshni, Bose–Einstein, acoustic/LO/full phonon linewidth, one-/two-channel Arrhenius PL quenching
- Multi-sample room-temperature overlays and comparisons
- Multi-sample temperature series, contour maps and parameter comparison plots
- CSV/XLS/XLSX/TXT/DAT input, `.plproj` projects, Excel/CSV/JSON/300 dpi PNG/vector PDF export
- Wavelength-to-energy Jacobian correction

## Windows quick start

1. Install 64-bit Python 3.11 and select **Add Python to PATH**.
2. Extract the ZIP.
3. Double-click `run_windows.bat`.
4. Add spectra. Filenames containing `80K`, `300K`, etc. are parsed automatically.
5. Edit Condition, Sample ID and Temperature in the table as needed.
6. Click **Batch fit**, inspect plots, then **Export**.

## Input examples

One spectrum per file:

```csv
Wavelength_nm,PL_Intensity
700,10
701,12
...
```

Recommended filenames: `AS_80K.csv`, `AS_100K.csv`, `CP20_80K.csv`.

## Scientific cautions

- Final fitting uses unsmoothed data; smoothing is used only for initial peak detection.
- A lower BIC does not itself prove a physical second emissive state.
- Arrhenius output is labeled PL-quenching activation energy; it is not automatically a trap depth or exciton binding energy.
- Full phonon and two-channel Arrhenius models display warnings when the number or span of temperature points is insufficient.

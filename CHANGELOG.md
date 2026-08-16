# Changelog

## Unreleased
- Added immutable per-record IDs across projects, background fitting, checkpoints, plotting selection, and export mapping.
- Made spectrum exports honor the Export checkbox consistently and added isolated timestamped datasets with manifests.
- Added fitting provenance, Origin-ready pure/display peak components, safer Windows filenames, and optional legacy Excel curve sheets.
- Added Windows GitHub Actions tests and export-identity/reproducibility regression coverage.
- Moved spectrum and temperature batch fitting off the Qt GUI thread into one serial background worker.
- Added per-file progress, elapsed time, ETA, cooperative cancellation, failure isolation, and durable per-file checkpoints.
- Added phased parse/preprocess/initial-guess/optimization/plot/export timing logs and explicit Matplotlib canvas/figure disposal.
- Added a 79-file ASC stress test covering event-loop responsiveness, cancellation, bad-file continuation, checkpoints, and working-set growth.
- Added integrated ASC spectrum import with instrument metadata preservation, mixed-format batch support, and validation for malformed ASC files.
- Added a dedicated Windows setup script for first installation and environment repair.
- Kept the daily Windows launcher isolated from environment creation and dependency installation.
- Added development requirements and repeatable isolated tests for Windows setup and launcher behavior.
- Updated Windows installation, troubleshooting, and contributor documentation.

## 0.4.0
- First complete working release.
- Multi-sample room-temperature and temperature-dependent PL batch analysis.
- Peak and temperature fitting, interactive GUI, project files and publication-ready exports.

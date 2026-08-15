# AGENTS.md

These instructions apply to the entire repository. Follow them for every task in this working tree unless the user gives more specific instructions.

## Repository overview

This repository contains a Windows-oriented PySide6 desktop application for batch analysis of steady-state perovskite photoluminescence spectra.

- `app.py`: GUI entry point and workflow orchestration, including file import, project save/load, fitting, plotting, and export actions.
- `pl_core.py`: spectrum parsing and preparation, wavelength/energy conversion, peak fitting, model selection, temperature-dependent fitting, statistics, and result data structures. Treat changes here as scientific-calculation changes.
- `plotting.py`: Matplotlib figure creation for fits, overlays, parameter trends, and contour maps.
- `export_manager.py`: Excel, CSV, JSON, PNG, and PDF export.
- `tests/test_core.py`: current pytest coverage for a Gaussian peak fit and a linear temperature fit.
- `examples/`: tracked example CSV spectra using `Wavelength_nm,PL_Intensity` columns and temperature-bearing filenames.
- `requirements.txt`: project dependency source of truth.
- `run_windows.bat`: end-user Windows launcher. It may create `.venv`, install requirements, and start `app.py`; do not use it as a routine Codex validation command because it mutates the environment and launches the GUI.
- `README.md` and `CHANGELOG.md`: user-facing usage, scientific cautions, and release information.

Do not invent packages, services, test suites, build systems, or application layers that are not present in the working tree. Reinspect the repository when its structure changes.

## Required work-start protocol

GitHub is the code synchronization source of truth because this repository may be used from multiple Windows computers. At the start of every new modification task, before editing files:

1. Obtain the Windows hostname dynamically with `hostname`; never hard-code a machine name.
2. Run `git status --short --branch`.
3. Run `git branch --show-current`.
4. Run `git rev-parse --short HEAD`.
5. Run `git fetch origin`.
6. Inspect the local branch versus its upstream with `git status --short --branch` and `git rev-list --left-right --count 'HEAD...@{upstream}'`. The two counts are ahead and behind, respectively.

Record the host, absolute repository path, branch, and starting HEAD for the final report.

If the working tree is clean and the local branch is only behind its upstream, it may be synchronized with a fast-forward-only operation such as `git pull --ff-only`. If there are local changes, untracked user files, branch divergence, a missing upstream, or a likely conflict, do not force synchronization. Explain the state and choose a safe, non-overwriting approach or ask the user how to proceed.

## Python environment

The repository-local Windows virtual environment is `.venv\`. The repository documents Python 3.11; do not hard-code a Python patch release.

- Run Python with `.venv\Scripts\python.exe`.
- Run pip with `.venv\Scripts\python.exe -m pip`.
- Run pytest with `.venv\Scripts\python.exe -m pytest`.
- Do not install project dependencies with system Python.
- Do not delete, recreate, replace, or modify files inside `.venv` unless the user explicitly requests environment repair.
- Never commit `.venv`.
- Use `requirements.txt` as the dependency source of truth. If a task genuinely requires a new dependency, update `requirements.txt` in the same change and explain why.
- Do not silently install packages just to make a check pass. Report a missing dependency, or obtain the user's approval when installation is needed.

## Git and file safety

- Preserve all pre-existing working-tree changes and untracked user files. Do not overwrite, revert, stage, or include unrelated changes.
- Make the smallest change needed for the requested result; avoid unrelated cleanup or broad refactoring.
- Do not delete files unless the task explicitly requires their removal and the exact targets have been verified.
- Never use `git reset --hard`.
- Never use `git clean -fd`, `git clean -fdx`, or an equivalent destructive cleanup.
- Do not force-push.
- Do not rebase, amend, squash, or otherwise rewrite history unless the user explicitly requests it.
- Do not commit `.venv`, `__pycache__`, bytecode, temporary files, generated caches, credentials, secrets, or unrelated/generated large files.
- Before and after edits, use `git status` and focused diffs to distinguish task changes from pre-existing changes.

## Code modification rules

- Prefer minimal, targeted edits and retain the existing UI and feature behavior unless the task explicitly changes them.
- Do not casually change accepted input formats, `.plproj` data, exported Excel/CSV/JSON fields, plot output, filenames, or analysis defaults.
- Be especially conservative with wavelength-to-energy conversion, Jacobian correction, peak line shapes, fit bounds and initialization, model selection, uncertainty/statistical calculations, and temperature-dependent models in `pl_core.py`.
- Scientific or data-format changes require an explicit rationale, focused regression coverage, and comparison against known behavior or analytically controlled data where possible.
- Do not use fabricated data to conceal a real defect. Synthetic data is acceptable only as an explicit, controlled test fixture.
- Do not weaken assertions, lower scientific tolerances without justification, delete failing tests, skip relevant tests, or change production behavior merely to manufacture a passing result.
- Keep imports and startup compatible with the existing Windows/PySide6 entry point.

## Validation

Validate every code change with the checks actually available in the repository. Run commands from the repository root using the local virtual environment.

Primary test command:

```powershell
.venv\Scripts\python.exe -m pytest
```

Basic syntax and import checks:

```powershell
.venv\Scripts\python.exe -m py_compile app.py pl_core.py plotting.py export_manager.py
.venv\Scripts\python.exe -c "import app; import pl_core; import plotting; import export_manager"
```

For GUI-affecting changes, also perform the safest applicable startup smoke test. At minimum verify that `app.py` imports without an immediate exception; when a display session is available and launching is safe, confirm that the application can create its main window without an immediate crash. Do not leave a GUI process running unattended.

Add focused tests for changed behavior when practical. Do not claim a command passed unless it was actually run. In the final report, give each executed command, passed/failed counts, warnings, skipped checks and reasons, and unresolved issues. Documentation-only changes still require an appropriate verification of the changed file and Git state; do not pretend that unchanged application behavior was newly tested if the tests were not run.

## Commit and push workflow

Do not commit or push unless the user explicitly requests it or an established repository workflow explicitly requires automatic submission. When authorized, use this order:

1. Complete the requested edits.
2. Run relevant validation.
3. Review `git diff` and, after staging, `git diff --cached`.
4. Run `git status --short --branch` and inspect the exact staged file list.
5. Confirm that `.venv`, `__pycache__`, temporary/generated files, large artifacts, credentials, secrets, and unrelated files are not staged.
6. Commit with a task-specific message.
7. Run `git fetch origin` again and recheck ahead/behind before pushing, so another computer's new commits are not overwritten.
8. If the remote advanced or the branches diverged, stop and handle the state safely; do not force-push or overwrite it.
9. Push normally to the intended upstream and verify the resulting status.

## Final report

Every completed task must end with a concise report in this shape, using values obtained at runtime:

```text
Host: <Windows hostname>
Repository: D:\Github\Perovskite_PL_Batch_Analyzer
Branch: <current branch>
HEAD: <current short commit>

Changed:
- <file and purpose, or None>

Validation:
- <actual command/check>: <passed/failed counts and warnings>

Git:
- Commit: <hash, or Not created>
- Push: <status, or Not requested>
- Working tree: <clean or concise status>

Remaining issues:
- None
```

If anything failed, was skipped, remains unresolved, or is affected by pre-existing changes, replace `None` with a direct explanation.

@echo off
setlocal
cd /d "%~dp0"

if not exist "%~dp0.venv\Scripts\python.exe" (
  goto environment_missing
)

"%~dp0.venv\Scripts\python.exe" -c "import sys" >nul 2>&1
if errorlevel 1 goto environment_broken

"%~dp0.venv\Scripts\python.exe" -c "import sys; raise SystemExit(0 if sys.version_info[:2] == (3, 11) else 1)" >nul 2>&1
if errorlevel 1 goto environment_wrong_version

"%~dp0.venv\Scripts\python.exe" -c "import numpy, pandas, scipy, matplotlib, openpyxl, PySide6, xlrd; import app, pl_core, plotting, export_manager"
if errorlevel 1 goto dependencies_missing

echo ========================================
echo Perovskite PL Batch Analyzer
echo ========================================
echo Repository: %CD%
echo Python: "%~dp0.venv\Scripts\python.exe"
"%~dp0.venv\Scripts\python.exe" --version
if errorlevel 1 (
  goto environment_broken
)
echo Starting application...
echo ========================================

"%~dp0.venv\Scripts\python.exe" "%~dp0app.py"
set "APP_EXIT_CODE=%ERRORLEVEL%"

if not "%APP_EXIT_CODE%"=="0" (
  echo.
  echo Application exited with an error.
  echo Exit code: %APP_EXIT_CODE%
  pause
  exit /b %APP_EXIT_CODE%
)

echo.
echo Application closed normally.
pause
exit /b 0

:environment_missing
echo ERROR: The repository-local virtual environment was not found.
echo Expected Python executable: "%~dp0.venv\Scripts\python.exe"
echo Run setup_windows.bat before starting the application.
pause
exit /b 1

:environment_broken
echo ERROR: The repository-local Python interpreter could not run.
echo Run setup_windows.bat to install or repair the environment.
pause
exit /b 1

:environment_wrong_version
echo ERROR: The repository-local virtual environment does not use Python 3.11.
echo Run setup_windows.bat to repair the environment.
pause
exit /b 1

:dependencies_missing
echo.
echo ERROR: Required runtime dependencies or application imports are unavailable.
echo Run setup_windows.bat to install or repair the environment.
pause
exit /b 1

@echo off
setlocal
cd /d "%~dp0"

echo ========================================
echo Perovskite PL Batch Analyzer Setup
echo ========================================
echo Repository: %CD%
echo.

if exist "%~dp0.venv" goto validate_existing_venv
goto find_python

:find_python
echo Looking for 64-bit Python 3.11...
py -3.11 -c "import struct, sys; raise SystemExit(0 if sys.version_info[:2] == (3, 11) and struct.calcsize('P') * 8 == 64 else 1)" >nul 2>&1
if not errorlevel 1 goto create_venv_with_py

python -c "import struct, sys; raise SystemExit(0 if sys.version_info[:2] == (3, 11) and struct.calcsize('P') * 8 == 64 else 1)" >nul 2>&1
if not errorlevel 1 goto create_venv_with_python
goto python_not_found

:create_venv_with_py
echo Creating repository-local virtual environment...
py -3.11 -m venv "%~dp0.venv"
set "SETUP_EXIT_CODE=%ERRORLEVEL%"
if not "%SETUP_EXIT_CODE%"=="0" goto venv_creation_failed
goto validate_venv

:create_venv_with_python
echo Creating repository-local virtual environment...
python -m venv "%~dp0.venv"
set "SETUP_EXIT_CODE=%ERRORLEVEL%"
if not "%SETUP_EXIT_CODE%"=="0" goto venv_creation_failed
goto validate_venv

:validate_existing_venv
if not exist "%~dp0.venv\Scripts\python.exe" goto existing_venv_broken
goto validate_venv

:validate_venv
"%~dp0.venv\Scripts\python.exe" -c "import sys" >nul 2>&1
if errorlevel 1 goto existing_venv_broken

"%~dp0.venv\Scripts\python.exe" -c "import sys; raise SystemExit(0 if sys.version_info[:2] == (3, 11) else 1)" >nul 2>&1
if errorlevel 1 goto existing_venv_wrong_version

"%~dp0.venv\Scripts\python.exe" -c "import os, sys; expected = os.path.normcase(os.path.abspath(os.path.join(os.getcwd(), r'.venv\Scripts\python.exe'))); actual = os.path.normcase(os.path.abspath(sys.executable)); raise SystemExit(0 if actual == expected else 1)" >nul 2>&1
if errorlevel 1 goto existing_venv_wrong_path

echo Installing runtime requirements...
"%~dp0.venv\Scripts\python.exe" -m pip install -r "%~dp0requirements.txt"
set "SETUP_EXIT_CODE=%ERRORLEVEL%"
if not "%SETUP_EXIT_CODE%"=="0" goto requirements_failed

echo Validating runtime dependencies and application imports...
"%~dp0.venv\Scripts\python.exe" -c "import numpy, pandas, scipy, matplotlib, openpyxl, PySide6, xlrd; import app, pl_core, plotting, export_manager"
set "SETUP_EXIT_CODE=%ERRORLEVEL%"
if not "%SETUP_EXIT_CODE%"=="0" goto import_validation_failed

echo.
echo ========================================
echo Repository: %CD%
echo Python executable: "%~dp0.venv\Scripts\python.exe"
echo Python version:
"%~dp0.venv\Scripts\python.exe" --version
echo Setup completed successfully.
echo ========================================
pause
exit /b 0

:python_not_found
echo.
echo ERROR: Compatible Python was not found.
echo Install 64-bit Python 3.11, then run setup_windows.bat again.
echo Other Python versions are not supported by this setup.
pause
exit /b 1

:venv_creation_failed
echo.
echo ERROR: Failed to create the repository-local virtual environment.
echo Exit code: %SETUP_EXIT_CODE%
echo Expected environment: "%~dp0.venv"
pause
exit /b %SETUP_EXIT_CODE%

:existing_venv_broken
echo.
echo ERROR: The existing repository-local virtual environment is incomplete or damaged.
echo Expected Python executable: "%~dp0.venv\Scripts\python.exe"
echo Move or remove "%~dp0.venv" manually, then run setup_windows.bat again.
echo This setup will not delete or overwrite the existing environment.
pause
exit /b 1

:existing_venv_wrong_version
echo.
echo ERROR: The existing repository-local virtual environment does not use Python 3.11.
echo Move or remove "%~dp0.venv" manually, then run setup_windows.bat again.
echo This setup will not delete or overwrite the existing environment.
pause
exit /b 1

:existing_venv_wrong_path
echo.
echo ERROR: The virtual environment interpreter is not repository-local.
echo Expected Python executable: "%~dp0.venv\Scripts\python.exe"
echo Move or remove "%~dp0.venv" manually, then run setup_windows.bat again.
echo This setup will not delete or overwrite the existing environment.
pause
exit /b 1

:requirements_failed
echo.
echo ERROR: Failed to install requirements.txt.
echo Exit code: %SETUP_EXIT_CODE%
echo Check the network connection and the error messages above, then rerun setup_windows.bat.
pause
exit /b %SETUP_EXIT_CODE%

:import_validation_failed
echo.
echo ERROR: Setup completed installation, but dependency or application import validation failed.
echo Exit code: %SETUP_EXIT_CODE%
echo Review the error messages above, then rerun setup_windows.bat.
pause
exit /b %SETUP_EXIT_CODE%

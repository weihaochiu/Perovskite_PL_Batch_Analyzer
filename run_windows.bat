@echo off
setlocal
cd /d "%~dp0"

if not exist "%~dp0.venv\Scripts\python.exe" (
  echo ERROR: Repository-local Python interpreter was not found.
  echo Expected virtual environment: "%~dp0.venv"
  echo Expected Python executable: "%~dp0.venv\Scripts\python.exe"
  echo The application will not fall back to system Python.
  pause
  exit /b 1
)

echo ========================================
echo Perovskite PL Batch Analyzer
echo ========================================
echo Repository: %CD%
echo Python: "%~dp0.venv\Scripts\python.exe"
"%~dp0.venv\Scripts\python.exe" --version
if errorlevel 1 (
  echo ERROR: Failed to run the repository-local Python interpreter.
  pause
  exit /b 1
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

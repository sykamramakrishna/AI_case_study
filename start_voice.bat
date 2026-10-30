@echo off
cd /d "%~dp0"
py -3.12 main.py --voice --live --speak
if errorlevel 1 (
  echo.
  echo Something went wrong. Running the voice check...
  py -3.12 main.py --check
)
pause

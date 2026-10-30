@echo off
cd /d "%~dp0"
echo Installing Python libraries...
py -3.12 -m pip install -r requirements.txt -r requirements-local-ai.txt
if errorlevel 1 (
  echo.
  echo Install failed. Make sure Python 3.12 is installed from python.org.
  pause
  exit /b 1
)
echo.
echo Checking the AI model...
py -3.12 main.py --ai-check
echo.
echo Setup finished. Next time just double-click start_app_ai.bat
pause

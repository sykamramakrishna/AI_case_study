@echo off
cd /d "%~dp0"
py -3.12 main.py --voice --live --speak --llm
pause

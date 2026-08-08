@echo off
rem Dry-run the brush_pm session in mock mode (no camera needed)
cd /d "%~dp0..\.."
.venv\Scripts\python -m agent.main --mock --now brush_pm
pause

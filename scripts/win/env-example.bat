@echo off
rem Regenerate .env.example from config/env-schema.json (refuses while the manifest disagrees with the code)
cd /d "%~dp0..\.."
.venv\Scripts\python -m leafi env-example
pause

@echo off
rem Run unit tests
cd /d "%~dp0..\.."
.venv\Scripts\python -m pytest -q
pause

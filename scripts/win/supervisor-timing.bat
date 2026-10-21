@echo off
rem Supervision timings in use after validation (read-only, ADR-0016): values, derived times, conflicts
cd /d "%~dp0..\.."
.venv\Scripts\python.exe -m leafi timing

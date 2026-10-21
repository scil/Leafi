@echo off
rem Configuration checks once (read-only, ADR-0016): ok / FAIL per check; raises no alert
cd /d "%~dp0..\.."
.venv\Scripts\python.exe -m leafi checks

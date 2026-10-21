@echo off
rem Supervision status (read-only, ADR-0016): each service's recovery budget, derived recovery and give-up times,
rem failing configuration checks, unsent alerts
cd /d "%~dp0..\.."
.venv\Scripts\python.exe -m leafi alert --status

@echo off
rem Deliver alerts that are due now (ADR-0016): a toast for each new one, Telegram oldest-first; the supervisor
rem does this every 10 s, so this is for when it is stopped
cd /d "%~dp0..\.."
.venv\Scripts\python.exe -m leafi alert --drain

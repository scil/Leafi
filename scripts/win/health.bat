@echo off
rem System health snapshot: stream / Frigate / containers / recent errors
cd /d "%~dp0..\.."
powershell -NoProfile -ExecutionPolicy Bypass -File "scripts\win\health.ps1"
pause

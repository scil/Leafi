@echo off
rem Register and start the leafi-supervisor logon task (ADR-0016; changes Windows configuration)
cd /d "%~dp0..\.."
powershell.exe -NoProfile -ExecutionPolicy Bypass -File scripts\win\install-tasks.ps1

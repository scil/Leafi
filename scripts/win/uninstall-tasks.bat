@echo off
rem Stop the supervisor and remove the leafi-supervisor logon task (ADR-0016); go2rtc goes back to go2rtc-host.bat
cd /d "%~dp0..\.."
powershell.exe -NoProfile -ExecutionPolicy Bypass -File scripts\win\uninstall-tasks.ps1

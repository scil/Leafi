@echo off
rem Stop all services: the Leafi supervisor (with go2rtc and the habit agent) and the containers
cd /d "%~dp0..\.."
powershell -NoProfile -ExecutionPolicy Bypass -File "scripts\win\stop-tasks.ps1"
docker compose down
echo.
echo [OK] all services stopped. The logon tasks start them again at the next logon (or run up.bat).
pause

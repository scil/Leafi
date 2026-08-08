@echo off
rem Stop all services
cd /d "%~dp0..\.."
docker compose down
echo.
echo [OK] all services stopped.
pause

@echo off
rem Start all services: Frigate (incl. go2rtc) + mosquitto
cd /d "%~dp0..\.."
docker compose up -d
echo.
echo [OK] go2rtc:  http://127.0.0.1:1984
echo [OK] Frigate: http://127.0.0.1:5000
pause

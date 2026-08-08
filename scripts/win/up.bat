@echo off
rem Start all services: host go2rtc (camera P2P) + Frigate + mosquitto
cd /d "%~dp0..\.."
call "%~dp0go2rtc-host.bat"
docker compose up -d
echo.
echo [OK] go2rtc host: http://127.0.0.1:2984
echo [OK] Frigate:     http://127.0.0.1:15000
pause

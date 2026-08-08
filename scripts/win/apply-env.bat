@echo off
rem Apply .env changes: recreate frigate container (plain restart does NOT re-read .env)
cd /d "%~dp0..\.."
docker compose up -d --force-recreate frigate
echo.
echo [OK] .env applied, frigate recreated.
pause

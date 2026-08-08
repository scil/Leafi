@echo off
rem Follow frigate logs (Ctrl+C to quit)
cd /d "%~dp0..\.."
docker compose logs -f --tail 100 frigate
pause

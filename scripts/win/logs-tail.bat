@echo off
rem Bounded log dump (last 60 lines) - safe for Obsidian Shell commands, unlike logs.bat which follows forever
cd /d "%~dp0..\.."
echo ===== Frigate (last 60) =====
docker compose logs --tail 60 --no-log-prefix frigate
echo.
echo ===== host go2rtc (last 20) =====
powershell -NoProfile -Command "if (Test-Path 'tools\go2rtc\host.log') { Get-Content 'tools\go2rtc\host.log' -Tail 20 } else { 'no host.log' }"
pause

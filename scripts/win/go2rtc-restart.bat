@echo off
rem Restart the host go2rtc instance (TD-25: viewing the camera in the Mi Home app kills its P2P producer
rem until go2rtc restarts). Stops only the go2rtc.exe started from this repository, then starts it again.
rem Silent: nothing is pushed to the camera speaker.
cd /d "%~dp0..\.."
powershell -NoProfile -Command "$exe = (Resolve-Path 'tools\go2rtc\go2rtc.exe').Path; $p = Get-Process go2rtc -ErrorAction SilentlyContinue | Where-Object { $_.Path -eq $exe }; if ($p) { $p | Stop-Process -Force; $p | Wait-Process -Timeout 10 -ErrorAction SilentlyContinue; Write-Host '[OK] go2rtc host stopped' } else { Write-Host '[--] go2rtc host was not running' }"
call "%~dp0go2rtc-host.bat"

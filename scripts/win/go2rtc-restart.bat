@echo off
rem Restart the host go2rtc instance (TD-25: viewing the camera in the Mi Home app kills its P2P producer).
rem With the leafi-watchdog task installed (ADR-0016) this only asks the watchdog to rearm: a fresh budget of
rem three restarts, the first one now. Without it, stops only this repository's go2rtc.exe and starts it again.
rem Silent: nothing is pushed to the camera speaker.
cd /d "%~dp0..\.."
powershell -NoProfile -Command "if (Get-ScheduledTask -TaskName 'leafi-watchdog' -ErrorAction SilentlyContinue) { try { Invoke-WebRequest -UseBasicParsing -Method Post -TimeoutSec 5 http://127.0.0.1:18771/rearm | Out-Null; Write-Host '[OK] watchdog rearmed: go2rtc restarts now' } catch { Write-Host '[X] the watchdog did not answer on 127.0.0.1:18771; see data\logs\watchdog.log and keep-watchdog.log' }; exit }; $exe = (Resolve-Path 'tools\go2rtc\go2rtc.exe').Path; $p = Get-Process go2rtc -ErrorAction SilentlyContinue | Where-Object { $_.Path -eq $exe }; if ($p) { $p | Stop-Process -Force; $p | Wait-Process -Timeout 10 -ErrorAction SilentlyContinue; Write-Host '[OK] go2rtc host stopped' } else { Write-Host '[--] go2rtc host was not running' }; & '%~dp0go2rtc-host.bat'"

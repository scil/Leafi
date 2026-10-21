# Stop the Leafi supervisor (ADR-0016): disable keep.ps1's task first, so neither keep.ps1 nor the 5-minute
# repeating trigger starts it again (up.bat / go2rtc-host.bat enable it), then stop the supervisor itself; its
# children (go2rtc, the habit agent, Ollama) die with it (Job Objects).
if (Get-ScheduledTask -TaskName "leafi-supervisor" -ErrorAction SilentlyContinue) {
    Disable-ScheduledTask -TaskName "leafi-supervisor" | Out-Null
    Stop-ScheduledTask -TaskName "leafi-supervisor"
    Write-Output "[OK] leafi-supervisor task disabled (up.bat enables it again)"
}
Get-CimInstance Win32_Process -Filter "Name='python.exe'" |
    Where-Object { $_.CommandLine -match '-m leafi supervisor' } |
    ForEach-Object { Stop-Process -Id $_.ProcessId -Force; Write-Output "[OK] stopped supervisor pid $($_.ProcessId)" }

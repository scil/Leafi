# Stop the Leafi supervisor (ADR-0016): keep.ps1's task first, so it does not restart the supervisor, then the
# supervisor itself; its children (go2rtc, the habit agent, Ollama) die with it (Job Objects).
if (Get-ScheduledTask -TaskName "leafi-supervisor" -ErrorAction SilentlyContinue) {
    Stop-ScheduledTask -TaskName "leafi-supervisor"
}
Get-CimInstance Win32_Process -Filter "Name='python.exe'" |
    Where-Object { $_.CommandLine -match '-m leafi supervisor' } |
    ForEach-Object { Stop-Process -Id $_.ProcessId -Force; Write-Output "[OK] stopped supervisor pid $($_.ProcessId)" }

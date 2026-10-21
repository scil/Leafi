# Stop the Leafi keepers and the processes they started (ADR-0016): the keeper first, so it does not restart
# its child, then the watchdog (go2rtc dies with it: Job Object) and the habit agent.
foreach ($task in @("leafi-watchdog", "leafi-habit-agent")) {
    if (Get-ScheduledTask -TaskName $task -ErrorAction SilentlyContinue) { Stop-ScheduledTask -TaskName $task }
}
Get-CimInstance Win32_Process -Filter "Name='python.exe'" |
    Where-Object { $_.CommandLine -match '-m (leafi watchdog|agent\.main)' } |
    ForEach-Object { Stop-Process -Id $_.ProcessId -Force; Write-Output "[OK] stopped pid $($_.ProcessId)" }

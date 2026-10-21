# Remove the Leafi logon tasks (ADR-0016) and stop what they started. go2rtc goes back to go2rtc-host.bat.
$repo = Split-Path (Split-Path $PSScriptRoot -Parent) -Parent
& (Join-Path $PSScriptRoot "stop-tasks.ps1")
foreach ($task in @("leafi-watchdog", "leafi-habit-agent")) {
    if (Get-ScheduledTask -TaskName $task -ErrorAction SilentlyContinue) {
        Unregister-ScheduledTask -TaskName $task -Confirm:$false
        Write-Output "[OK] removed $task"
    }
}

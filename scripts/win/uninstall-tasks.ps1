# Remove the Leafi logon task (ADR-0016) and stop the supervisor. go2rtc goes back to go2rtc-host.bat and the
# habit agent to being started by hand.
& (Join-Path $PSScriptRoot "stop-tasks.ps1")
if (Get-ScheduledTask -TaskName "leafi-supervisor" -ErrorAction SilentlyContinue) {
    Unregister-ScheduledTask -TaskName "leafi-supervisor" -Confirm:$false
    Write-Output "[OK] removed leafi-supervisor"
}

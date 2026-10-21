# Register the Leafi logon task (ADR-0016). Changes Windows configuration: the owner runs this, once.
#   leafi-supervisor  keep.ps1 -> python -m leafi supervisor, which keeps every service in SUPERVISE running
#                     (Docker Desktop, go2rtc, the habit agent, Frigate, mosquitto; Ollama when listed)
# Runs only while this user is logged on (toasts need the desktop), one instance, no time limit; Task Scheduler
# restarts keep.ps1 itself every minute if it ever exits. Undo: uninstall-tasks.ps1.
$repo = Split-Path (Split-Path $PSScriptRoot -Parent) -Parent
$keep = Join-Path $PSScriptRoot "keep.ps1"
$user = "$env:USERDOMAIN\$env:USERNAME"
$action = New-ScheduledTaskAction -Execute "powershell.exe" -WorkingDirectory $repo `
    -Argument "-NoProfile -ExecutionPolicy Bypass -WindowStyle Hidden -File `"$keep`""
$trigger = New-ScheduledTaskTrigger -AtLogOn -User $user
$settings = New-ScheduledTaskSettingsSet -MultipleInstances IgnoreNew -ExecutionTimeLimit ([TimeSpan]::Zero) `
    -RestartCount 999 -RestartInterval (New-TimeSpan -Minutes 1) -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries
$principal = New-ScheduledTaskPrincipal -UserId $user -LogonType Interactive -RunLevel Limited
Register-ScheduledTask -TaskName "leafi-supervisor" -Action $action -Trigger $trigger -Settings $settings `
    -Principal $principal -Description "Leafi: keep every service running (ADR-0016)" -Force | Out-Null
Write-Output "[OK] registered leafi-supervisor"
Start-ScheduledTask -TaskName "leafi-supervisor"
Write-Output "[OK] started leafi-supervisor (it takes over go2rtc and the habit agent; see data\logs\supervisor.log)"

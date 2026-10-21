# Register the Leafi logon task (ADR-0016). Changes Windows configuration: the owner runs this, once.
#   leafi-supervisor  keep.ps1 -> python -m leafi supervisor, which keeps every service in SUPERVISE running
#                     (Docker Desktop, go2rtc, Frigate, mosquitto, Gatus; the habit agent and Ollama when listed)
# Runs only while this user is logged on (toasts need the desktop), one instance, no time limit; a 5-minute
# repeating trigger relaunches keep.ps1 if it ever dies. Undo: uninstall-tasks.ps1.
$repo = Split-Path (Split-Path $PSScriptRoot -Parent) -Parent
$keep = Join-Path $PSScriptRoot "keep.ps1"
$user = "$env:USERDOMAIN\$env:USERNAME"
# conhost --headless: no window at all. `powershell -WindowStyle Hidden` is not enough when Windows Terminal is the
# default terminal (it ignores the flag and shows an empty window; closing it killed keep.ps1, 2026-10-21).
$action = New-ScheduledTaskAction -Execute "conhost.exe" -WorkingDirectory $repo `
    -Argument "--headless powershell.exe -NoProfile -ExecutionPolicy Bypass -File `"$keep`""
$logon = New-ScheduledTaskTrigger -AtLogOn -User $user
# Relaunch keep.ps1 within TASK_REPEAT_MIN (default 5) if it ever dies; IgnoreNew leaves a running one alone.
. (Join-Path $PSScriptRoot "timing.ps1")
$timing = Read-LeafiTiming $repo
$repeatMin = [int]$timing.TASK_REPEAT_MIN
Write-Output "[--] repeating trigger every $repeatMin min (from $($timing._source))"
$repeat = New-ScheduledTaskTrigger -Once -At (Get-Date) -RepetitionInterval (New-TimeSpan -Minutes $repeatMin)
$trigger = @($logon, $repeat)
$settings = New-ScheduledTaskSettingsSet -MultipleInstances IgnoreNew -ExecutionTimeLimit ([TimeSpan]::Zero) `
    -RestartCount 999 -RestartInterval (New-TimeSpan -Minutes 1) -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries
$principal = New-ScheduledTaskPrincipal -UserId $user -LogonType Interactive -RunLevel Limited
Register-ScheduledTask -TaskName "leafi-supervisor" -Action $action -Trigger $trigger -Settings $settings `
    -Principal $principal -Description "Leafi: keep every service running (ADR-0016)" -Force | Out-Null
Write-Output "[OK] registered leafi-supervisor"
Start-ScheduledTask -TaskName "leafi-supervisor"
Write-Output "[OK] started leafi-supervisor (it takes over go2rtc and keeps every service in SUPERVISE running; see data\logs\supervisor.log)"

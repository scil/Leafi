# Register the Leafi logon tasks (ADR-0016). Changes Windows configuration: the owner runs this, once.
#   leafi-watchdog     keep.ps1 watchdog     (the watchdog owns go2rtc from now on)
#   leafi-habit-agent  keep.ps1 habit-agent  (only with -HabitAgent)
# Each runs only while this user is logged on (toasts need the desktop), one instance, no time limit, and
# Task Scheduler restarts the keeper itself every minute if it ever exits. Undo: uninstall-tasks.ps1.
param([switch]$HabitAgent)
$repo = Split-Path (Split-Path $PSScriptRoot -Parent) -Parent
$keep = Join-Path $PSScriptRoot "keep.ps1"
$names = @("watchdog") + $(if ($HabitAgent) { @("habit-agent") } else { @() })
$user = "$env:USERDOMAIN\$env:USERNAME"
foreach ($n in $names) {
    $task = "leafi-$n"
    $action = New-ScheduledTaskAction -Execute "powershell.exe" -WorkingDirectory $repo `
        -Argument "-NoProfile -ExecutionPolicy Bypass -WindowStyle Hidden -File `"$keep`" -Name $n"
    $trigger = New-ScheduledTaskTrigger -AtLogOn -User $user
    $settings = New-ScheduledTaskSettingsSet -MultipleInstances IgnoreNew -ExecutionTimeLimit ([TimeSpan]::Zero) `
        -RestartCount 999 -RestartInterval (New-TimeSpan -Minutes 1) -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries
    $principal = New-ScheduledTaskPrincipal -UserId $user -LogonType Interactive -RunLevel Limited
    Register-ScheduledTask -TaskName $task -Action $action -Trigger $trigger -Settings $settings -Principal $principal `
        -Description "Leafi: keep $n running (ADR-0016)" -Force | Out-Null
    Write-Output "[OK] registered $task"
}
# Hand go2rtc over: stop a standalone go2rtc first (the watchdog would kill it anyway), then start the tasks.
$exe = (Resolve-Path (Join-Path $repo "tools\go2rtc\go2rtc.exe")).Path
Get-Process go2rtc -ErrorAction SilentlyContinue | Where-Object { $_.Path -eq $exe } | Stop-Process -Force
foreach ($n in $names) { Start-ScheduledTask -TaskName "leafi-$n"; Write-Output "[OK] started leafi-$n" }

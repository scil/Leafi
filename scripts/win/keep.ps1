# Outermost guard (ADR-0016): keep `python -m leafi supervisor` running. Started at logon by the Task Scheduler
# task that scripts\win\install-tasks.ps1 registers; run by hand only for a test. The supervisor keeps every
# other service running; this loop only restarts the supervisor itself.
# After an exit it starts it again after KEEP_BACKOFF_S (default 5 s, 30 s, 2 min, then 5 min); a run as long as
# KEEP_CRASH_WINDOW_MIN resets the backoff. KEEP_CRASH_EXITS exits within that window queue one supervisor alert
# and deliver it (python -m leafi alert, no supervisor needed). Values: timing.ps1 (validated by leafi timing).
$ErrorActionPreference = "Continue"
$repo = Split-Path (Split-Path $PSScriptRoot -Parent) -Parent
Set-Location $repo
$python = Join-Path $repo ".venv\Scripts\python.exe"
$logDir = Join-Path $repo "data\logs"
New-Item -ItemType Directory -Force $logDir | Out-Null
$log = Join-Path $logDir "keep-supervisor.log"

function Write-Keep([string]$msg) {
    if ((Test-Path $log) -and (Get-Item $log).Length -gt 1MB) { Move-Item -Force $log "$log.1" }
    Add-Content -Path $log -Value ("{0:yyyy-MM-dd HH:mm:ss} {1}" -f (Get-Date), $msg)
}

. (Join-Path $PSScriptRoot "timing.ps1")
$timing = Read-LeafiTiming $repo
$backoff = @($timing.KEEP_BACKOFF_S -split ',' | ForEach-Object { [double]$_ })
$crashExits = [int]$timing.KEEP_CRASH_EXITS
$windowMin = [double]$timing.KEEP_CRASH_WINDOW_MIN
Write-Keep ("timing from {0}: backoff {1} s, {2} exits in {3} min" -f $timing._source, ($backoff -join ','),
    $crashExits, $windowMin)

$exits = New-Object System.Collections.Generic.List[datetime]
$alerted = $false
$quick = 0
while ($true) {
    $started = Get-Date
    Write-Keep "start supervisor"
    # -NoNewWindow: share this keeper's headless console (install-tasks.ps1 starts it under conhost --headless);
    # a new console would open a visible Windows Terminal window when that is the default terminal.
    $p = Start-Process -FilePath $python -ArgumentList @("-m", "leafi", "supervisor") -WorkingDirectory $repo `
        -NoNewWindow -PassThru
    $p.WaitForExit()
    if ($p.ExitCode -eq 3) {
        # Another supervisor holds the lock (this keep.ps1 was relaunched while the old supervisor lives on):
        # not a crash; look again in a minute.
        Write-Keep "supervisor already running; waiting"
        Start-Sleep -Seconds 60
        continue
    }
    $ran = (Get-Date) - $started
    Write-Keep ("exit {0} after {1:N0} s" -f $p.ExitCode, $ran.TotalSeconds)
    if ($ran.TotalMinutes -ge $windowMin) { $quick = 0; $alerted = $false; $exits.Clear() }
    $exits.Add((Get-Date))
    $exits.RemoveAll({ param($t) $t -lt (Get-Date).AddMinutes(-$windowMin) }) | Out-Null
    if ($exits.Count -ge $crashExits -and -not $alerted) {
        Write-Keep "$crashExits exits within $windowMin min: alerting"
        & $python -m leafi alert --insert supervisor down repeated_exits --drain *>> $log
        $alerted = $true
    }
    $wait = $backoff[[Math]::Min($quick, $backoff.Count - 1)]
    $quick++
    Start-Sleep -Seconds $wait
}

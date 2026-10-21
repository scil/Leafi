# Keep one Leafi process running (ADR-0016). Started at logon by the Task Scheduler tasks that
# scripts\win\install-tasks.ps1 registers; run by hand only for a test.
#   keep.ps1 watchdog      -> python -m leafi watchdog   (which owns go2rtc)
#   keep.ps1 habit-agent   -> python -m agent.main
# After an exit it starts the process again after 5 s, 30 s, 2 min, then every 5 min; a run of 30 min resets
# the backoff. Three exits within 30 min queue one keeper-<name> alert and deliver it (python -m leafi alert).
param([Parameter(Mandatory)][ValidateSet("watchdog", "habit-agent")][string]$Name)
$ErrorActionPreference = "Continue"
$repo = Split-Path (Split-Path $PSScriptRoot -Parent) -Parent
Set-Location $repo
$python = Join-Path $repo ".venv\Scripts\python.exe"
$argsFor = @{ "watchdog" = @("-m", "leafi", "watchdog"); "habit-agent" = @("-m", "agent.main") }
$logDir = Join-Path $repo "data\logs"
New-Item -ItemType Directory -Force $logDir | Out-Null
$log = Join-Path $logDir "keep-$Name.log"
$backoff = @(5, 30, 120, 300)

function Write-Keep([string]$msg) {
    if ((Test-Path $log) -and (Get-Item $log).Length -gt 1MB) { Move-Item -Force $log "$log.1" }
    Add-Content -Path $log -Value ("{0:yyyy-MM-dd HH:mm:ss} {1}" -f (Get-Date), $msg)
}

$exits = New-Object System.Collections.Generic.List[datetime]
$alerted = $false
$quick = 0
while ($true) {
    $started = Get-Date
    Write-Keep "start $Name"
    $p = Start-Process -FilePath $python -ArgumentList $argsFor[$Name] -WorkingDirectory $repo -WindowStyle Hidden -PassThru
    $p.WaitForExit()
    $ran = (Get-Date) - $started
    Write-Keep ("exit {0} after {1:N0} s" -f $p.ExitCode, $ran.TotalSeconds)
    if ($ran.TotalMinutes -ge 30) { $quick = 0; $alerted = $false; $exits.Clear() }
    $exits.Add((Get-Date))
    $exits.RemoveAll({ param($t) $t -lt (Get-Date).AddMinutes(-30) }) | Out-Null
    if ($exits.Count -ge 3 -and -not $alerted) {
        Write-Keep "3 exits within 30 min: alerting"
        & $python -m leafi alert --insert "keeper-$Name" down repeated_exits --drain *>> $log
        $alerted = $true
    }
    $wait = $backoff[[Math]::Min($quick, $backoff.Count - 1)]
    $quick++
    Start-Sleep -Seconds $wait
}

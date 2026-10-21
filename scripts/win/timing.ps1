# Supervision timings for the PowerShell scripts (ADR-0016), dot-sourced by keep.ps1 and install-tasks.ps1.
# Reads the validated values from `python -m leafi timing --env` with a 15 s limit; on failure or timeout the
# built-in defaults below are used, so a hung read never stops the supervisor from starting.
function Read-LeafiTiming([string]$Repo) {
    $values = @{ KEEP_BACKOFF_S = "5,30,120,300"; KEEP_CRASH_EXITS = "3"; KEEP_CRASH_WINDOW_MIN = "30";
                 TASK_REPEAT_MIN = "5"; _source = "defaults" }
    $python = Join-Path $Repo ".venv\Scripts\python.exe"
    $out = Join-Path ([IO.Path]::GetTempPath()) "leafi-timing-$PID.txt"
    try {
        $p = Start-Process -FilePath $python -ArgumentList @("-m", "leafi", "timing", "--env") -WorkingDirectory $Repo `
            -WindowStyle Hidden -PassThru -RedirectStandardOutput $out -ErrorAction Stop
        if (-not $p.WaitForExit(15000)) { $p.Kill(); throw "timed out after 15 s" }
        foreach ($line in Get-Content $out) {
            if ($line -match '^([A-Z_]+)=(.+)$') { $values[$Matches[1]] = $Matches[2]; $values._source = "leafi timing" }
        }
    } catch {
        $values._source = "defaults ($_)"
    } finally {
        Remove-Item $out -ErrorAction SilentlyContinue
    }
    return $values
}

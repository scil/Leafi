# Bring data\leafi.db to the latest schema (ADR-0018 section 7.2): first check that no Leafi process is running,
# then `leafi backup`, then `leafi migrate`. It never stops anything itself: with a process running it lists it and
# exits 1, and the owner stops services first (console 停止全部服务). `leafi migrate` also refuses on its own when
# another process holds the database (the exclusive lock), so a process this check misses cannot slip through.
$ErrorActionPreference = 'Stop'
Set-Location (Split-Path -Parent (Split-Path -Parent $PSScriptRoot))

$running = @(Get-CimInstance Win32_Process -Filter "Name='python.exe' OR Name='pythonw.exe'" |
    Where-Object { $_.CommandLine -match '-m\s+(leafi|agent)(\.|\s|$)' })
$task = Get-ScheduledTask -TaskName 'leafi-supervisor' -ErrorAction SilentlyContinue
if ($running.Count -gt 0 -or ($task -and $task.State -eq 'Running')) {
    # English only: Windows PowerShell 5.1 reads this file as ANSI (the console button's help line has the Chinese)
    Write-Output '[STOP] Leafi is still running; nothing was backed up or migrated. Stop all services, then retry.'
    if ($task -and $task.State -eq 'Running') { Write-Output '  task leafi-supervisor: Running' }
    foreach ($p in $running) { Write-Output "  pid $($p.ProcessId): $($p.CommandLine)" }
    exit 1
}

& .venv\Scripts\python.exe -m leafi backup
if ($LASTEXITCODE -ne 0) {
    Write-Output '[STOP] the backup failed; not migrated'
    exit $LASTEXITCODE
}
& .venv\Scripts\python.exe -m leafi migrate
exit $LASTEXITCODE

# Egress proof for the OCR evaluation trial.
#
#   scripts\evals\ocr\netwatch.ps1 -Seconds 300 [-Control]
#
# 1. Containers: lists each leafi-eval container's networks and tries an outbound TCP connect (1.1.1.1:443) from
#    inside every tool container; on the internal network each must fail. -Control also runs it from the gate,
#    which sits on the normal network, to show the test can succeed.
# 2. Host: polls the TCP table every second while you use the tools and prints every remote address that is not
#    loopback for the eval processes (the .venv-eval Python, FiftyOne's mongod). A line here means data left the
#    process for another machine; the summary line counts them.
param([int]$Seconds = 120, [switch]$Control)
$ErrorActionPreference = 'Stop'

$root = Split-Path (git -C $PSScriptRoot rev-parse --path-format=absolute --git-common-dir).Trim() -Parent
$venv = Join-Path $root '.venv-eval'
$log = Join-Path $root "cache\evals\logs\netwatch-$(Get-Date -Format yyyyMMdd-HHmmss).txt"

function Out-Both($s) { $s; Add-Content -LiteralPath $log -Value $s }

Out-Both "== containers"
$names = docker ps --filter label=com.docker.compose.project=leafi-eval --format '{{.Names}}'
foreach ($n in $names) {
    $nets = (docker inspect $n --format '{{range $k, $v := .NetworkSettings.Networks}}{{$k}} {{end}}').Trim()
    $isGate = $n -like '*-gate-*'
    if ($isGate -and -not $Control) { Out-Both ("{0,-32} {1,-36} (gate: inbound proxy)" -f $n, $nets); continue }
    # A throwaway busybox joins the container's own network namespace, so the test is the same for every image
    # (Phoenix's has no shell) and shows what that container can reach.
    $r = (docker run --rm --network "container:$n" busybox:1.37 sh -c 'nc -z -w 5 1.1.1.1 443 && echo REACHED || echo BLOCKED' 2>&1 |
        Select-Object -Last 1)
    Out-Both ("{0,-32} {1,-36} outbound: {2}" -f $n, $nets, $r)
}

Out-Both "== host processes for $Seconds s (Ctrl+C stops)"
$seen = @{}
$end = (Get-Date).AddSeconds($Seconds)
while ((Get-Date) -lt $end) {
    # The venv's python.exe is a launcher: the real interpreter is its child (the base Python), and that child's
    # command line need not name the venv. So: every process with a .venv-eval executable among its ancestors.
    $all = Get-CimInstance Win32_Process
    $byId = @{}; foreach ($p in $all) { $byId[[int]$p.ProcessId] = $p }
    $procs = foreach ($p in $all) {
        $q = $p; $hops = 0
        while ($q -and $hops -lt 12) {
            if ($q.ExecutablePath -and $q.ExecutablePath.StartsWith($venv)) { $p; break }
            if ($q.ParentProcessId -eq $q.ProcessId) { break }
            $q = $byId[[int]$q.ParentProcessId]; $hops++
        }
    }
    $ids = @($procs.ProcessId)
    if ($ids.Count) {
        Get-NetTCPConnection -OwningProcess $ids -ErrorAction SilentlyContinue |
            Where-Object { $_.RemoteAddress -notin '0.0.0.0', '::', '127.0.0.1', '::1' -and $_.RemoteAddress -notlike '127.*' } |
            ForEach-Object {
                $key = "$($_.OwningProcess) $($_.RemoteAddress):$($_.RemotePort)"
                if (-not $seen.ContainsKey($key)) {
                    $seen[$key] = 1
                    $p = $procs | Where-Object ProcessId -eq $_.OwningProcess
                    Out-Both ("{0:HH:mm:ss} OUTBOUND pid {1} {2} -> {3}:{4} {5}" -f (Get-Date), $_.OwningProcess,
                        $p.Name, $_.RemoteAddress, $_.RemotePort, $_.State)
                }
            }
    }
    Start-Sleep -Milliseconds 1000
}
Out-Both "== summary: $($seen.Count) outbound connection(s) from eval processes; log $log"

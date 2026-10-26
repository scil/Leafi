# OCR evaluation stack (trial). Every tool runs on this PC with telemetry off; see docs/research/2026-10-25-ocr-eval-tools-trial.md.
#
#   scripts\evals\ocr\stack.ps1 up        Docker: Langfuse, Phoenix, Label Studio behind the gate (internal network)
#   scripts\evals\ocr\stack.ps1 mlflow    MLflow server on 127.0.0.1:19500 (background, .venv-eval)
#   scripts\evals\ocr\stack.ps1 fiftyone  FiftyOne app on 127.0.0.1:19151 (background, .venv-eval)
#   scripts\evals\ocr\stack.ps1 status    which ports answer
#   scripts\evals\ocr\stack.ps1 down      stop the containers (data volumes stay)
#   scripts\evals\ocr\stack.ps1 start     up + mlflow + fiftyone (a server already answering is left alone)
#   scripts\evals\ocr\stack.ps1 stop      down + stop the MLflow and FiftyOne processes
#   scripts\evals\ocr\stack.ps1 add-snapshot   copy cache\checks\snapshot.jpg into the photo set, then labels push
#   scripts\evals\ocr\stack.ps1 labels-push | labels-pull   Label Studio tasks / annotations (labels.py)
#   scripts\evals\ocr\stack.ps1 tags | tags-list   change the condition tags and move given labels (tags.py menu) / list them
#   scripts\evals\ocr\stack.ps1 run -Pipeline default|probe-k2|scan-only [-Source all|camera|synthetic]
#                                   one evaluation run (run.py) over the photos that have page text
#   scripts\evals\ocr\stack.ps1 reset-results   stop everything, then delete every run's results (MLflow, FiftyOne,
#                                   Phoenix, Langfuse, ocr\runs); photos, truth.json and Label Studio stay
#
# Data and secrets live in the main checkout's gitignored cache\evals\ (stack.env is created on first `up`).
param(
    [Parameter(Mandatory)][ValidateSet('up', 'down', 'mlflow', 'fiftyone', 'status', 'start', 'stop', 'add-snapshot',
        'labels-push', 'labels-pull', 'tags', 'tags-list', 'run', 'reset-results')][string]$Action,
    [ValidateSet('default', 'probe-k2', 'scan-only')][string]$Pipeline = 'default',
    [ValidateSet('all', 'camera', 'synthetic')][string]$Source = 'all'
)
$ErrorActionPreference = 'Stop'

$here = $PSScriptRoot
$common = (git -C $here rev-parse --path-format=absolute --git-common-dir).Trim()
$root = Split-Path $common -Parent                       # the main checkout, also from a worktree
$evals = Join-Path $root 'cache\evals'
$photos = Join-Path $evals 'ocr\photos'
$envFile = Join-Path $evals 'stack.env'
$py = Join-Path $root '.venv-eval\Scripts\python.exe'
New-Item -ItemType Directory -Force $photos, (Join-Path $evals 'logs') | Out-Null

# Telemetry off for every host process started from here (the containers get theirs in docker-compose.yml).
$env:MLFLOW_DISABLE_TELEMETRY = 'true'
$env:DO_NOT_TRACK = 'true'
$env:FIFTYONE_DO_NOT_TRACK = 'true'
$env:MLFLOW_DISABLE_AGENT_HINT = '1'
$env:FIFTYONE_DATABASE_DIR = Join-Path $evals 'fiftyone\db'

function New-Secret([int]$bytes = 24) {
    $b = [byte[]]::new($bytes); [Security.Cryptography.RandomNumberGenerator]::Fill($b)
    -join ($b | ForEach-Object { $_.ToString('x2') })
}

function Write-StackEnv {
    if (Test-Path $envFile) { return }
    $lines = @(
        "EVAL_PHOTOS=$photos"
        "POSTGRES_PASSWORD=$(New-Secret)"
        "CLICKHOUSE_PASSWORD=$(New-Secret)"
        "MINIO_ROOT_PASSWORD=$(New-Secret)"
        "REDIS_AUTH=$(New-Secret)"
        "NEXTAUTH_SECRET=$(New-Secret)"
        "LANGFUSE_SALT=$(New-Secret)"
        "LANGFUSE_ENCRYPTION_KEY=$(New-Secret 32)"
        "LANGFUSE_PUBLIC_KEY=pk-lf-$(New-Secret 16)"
        "LANGFUSE_SECRET_KEY=sk-lf-$(New-Secret 16)"
        "LANGFUSE_USER_PASSWORD=$(New-Secret 12)"
        "LABEL_STUDIO_PASSWORD=$(New-Secret 12)"
        "LABEL_STUDIO_TOKEN=$(New-Secret 20)"
    )
    Set-Content -LiteralPath $envFile -Value $lines -Encoding utf8NoBOM
    Write-Host "Wrote $envFile (local test secrets; the UI logins are owner@leafi.test with the *_PASSWORD values)."
}

function Test-Port([int]$port) {
    $c = [Net.Sockets.TcpClient]::new()
    try { $c.ConnectAsync('127.0.0.1', $port).Wait(500) -and $c.Connected } catch { $false } finally { $c.Dispose() }
}

function Start-Detached([string]$cmdline, [string]$log) {
    # Win32_Process.Create: a new process that inherits no handle of ours. Start-Process would hand the server our
    # stdout pipe, and a caller reading that pipe (the Obsidian console, `| Select`) would wait for the server to exit.
    # The environment comes from the WMI service, not from us, so the telemetry switches go on the command line.
    $vars = 'set MLFLOW_DISABLE_TELEMETRY=true&& set DO_NOT_TRACK=true&& set FIFTYONE_DO_NOT_TRACK=true&& ' +
            "set MLFLOW_DISABLE_AGENT_HINT=1&& set FIFTYONE_DATABASE_DIR=$env:FIFTYONE_DATABASE_DIR&& "
    $full = "cmd.exe /d /c `"$vars$cmdline > `"$log`" 2>&1`""
    $r = Invoke-CimMethod -ClassName Win32_Process -MethodName Create -Arguments @{ CommandLine = $full; CurrentDirectory = $root }
    if ($r.ReturnValue -ne 0) { throw "Win32_Process.Create returned $($r.ReturnValue)" }
}

function Start-MLflow {
    if (Test-Port 19500) { Write-Host 'MLflow: already up, http://127.0.0.1:19500'; return }
    $m = Join-Path $evals 'mlflow'
    New-Item -ItemType Directory -Force $m | Out-Null
    $db = 'sqlite:///' + ((Join-Path $m 'mlflow.db') -replace '\\', '/')
    Start-Detached ("`"$py`" -m mlflow server --host 127.0.0.1 --port 19500 --workers 1 --backend-store-uri $db " +
        "--artifacts-destination `"$(Join-Path $m 'artifacts')`"") (Join-Path $evals 'logs\mlflow.log')
    Write-Host 'MLflow: http://127.0.0.1:19500'
}

function Start-FiftyOne {
    if (Test-Port 19151) { Write-Host 'FiftyOne: already up, http://127.0.0.1:19151'; return }
    Start-Detached "`"$py`" `"$(Join-Path $here 'fo_app.py')`"" (Join-Path $evals 'logs\fiftyone.log')
    Write-Host 'FiftyOne: http://127.0.0.1:19151 (ready after about 20 s)'
}

function Stop-HostServers {
    # The top .venv-eval launcher of each server; /T takes its children (the base Python, uvicorn, mongod) with it.
    $venv = Join-Path $root '.venv-eval'
    $all = Get-CimInstance Win32_Process
    $tops = $all | Where-Object {
        $_.ExecutablePath -and $_.ExecutablePath.StartsWith($venv) -and $_.CommandLine -and
        ($_.CommandLine.Contains('mlflow server') -or $_.CommandLine.Contains('fo_app.py'))
    }
    $ids = @($tops.ProcessId)
    $tops = $tops | Where-Object { $ids -notcontains $_.ParentProcessId }
    foreach ($p in $tops) { taskkill /T /F /PID $p.ProcessId | Out-Null; Write-Host "stopped pid $($p.ProcessId)" }
    if (-not $tops) { Write-Host 'MLflow / FiftyOne: not running' }
}

function Show-Status {
    foreach ($p in @(@('Langfuse', 19300), @('Langfuse MinIO', 19090), @('Phoenix', 19006), @('Label Studio', 19080),
            @('MLflow', 19500), @('FiftyOne', 19151))) {
        '{0,-15} {1,5}  {2}' -f $p[0], $p[1], $(if (Test-Port $p[1]) { 'up' } else { 'down' })
    }
}

function Invoke-Py([string[]]$ArgList) {
    & $py -W ignore @ArgList
    if ($LASTEXITCODE) { exit $LASTEXITCODE }
}

$compose = @('compose', '-f', (Join-Path $here 'docker-compose.yml'), '--env-file', $envFile)
switch ($Action) {
    'up' { Write-StackEnv; docker @compose up -d }
    'down' { docker @compose down }
    'mlflow' { Start-MLflow }
    'fiftyone' { Start-FiftyOne }
    'status' { Show-Status }
    'start' {
        Write-StackEnv
        docker @compose up -d 2>&1 | Select-Object -Last 1
        Start-MLflow
        Start-FiftyOne
        for ($t = 0; $t -lt 60 -and -not ((Test-Port 19500) -and (Test-Port 19151)); $t += 3) { Start-Sleep -Seconds 3 }
        Show-Status
    }
    'stop' { docker @compose down 2>&1 | Select-Object -Last 1; Stop-HostServers }
    'add-snapshot' {
        $src = Join-Path $root 'cache\checks\snapshot.jpg'
        if (-not (Test-Path $src)) { Write-Host "No snapshot yet: take one with the console's camera snapshot button."; exit 1 }
        $cam = Join-Path $photos 'camera'
        New-Item -ItemType Directory -Force $cam | Out-Null
        $hash = (Get-FileHash $src).Hash
        $same = Get-ChildItem $cam -File | Where-Object { (Get-FileHash $_.FullName).Hash -eq $hash } | Select-Object -First 1
        if ($same) { Write-Host "Already in the set as camera/$($same.Name)"; exit 0 }
        $name = 'snap-' + (Get-Item $src).LastWriteTime.ToString('yyyyMMdd-HHmmss') + '.jpg'
        Copy-Item $src (Join-Path $cam $name)
        Write-Host "Added camera/$name"
        Invoke-Py @((Join-Path $here 'labels.py'), 'push')
    }
    'labels-push' { Invoke-Py @((Join-Path $here 'labels.py'), 'push') }
    'labels-pull' { Invoke-Py @((Join-Path $here 'labels.py'), 'pull') }
    'tags' { Invoke-Py @((Join-Path $here 'tags.py')) }
    'tags-list' { Invoke-Py @((Join-Path $here 'tags.py'), 'list') }
    'run' { Invoke-Py @((Join-Path $here 'run.py'), '--pipeline', $Pipeline, '--source', $Source) }
    'reset-results' {
        docker info --format '{{.ServerVersion}}' *> $null
        if ($LASTEXITCODE) { Write-Host 'Docker is not running: start Docker Desktop, then click again.'; exit 1 }
        docker @compose down 2>&1 | Select-Object -Last 1
        Stop-HostServers
        # Langfuse (postgres, clickhouse, minio, redis) and Phoenix volumes; label_studio_data holds the labels.
        foreach ($v in docker volume ls -q --filter 'label=com.docker.compose.project=leafi-eval') {
            $key = docker volume inspect -f '{{index .Labels "com.docker.compose.volume"}}' $v
            if ($key -eq 'label_studio_data') { continue }
            docker volume rm $v | Out-Null
            Write-Host "deleted volume $v"
        }
        foreach ($d in @((Join-Path $evals 'mlflow'), (Join-Path $evals 'fiftyone'), (Join-Path $evals 'ocr\runs'))) {
            if (Test-Path $d) { Remove-Item -LiteralPath $d -Recurse -Force; Write-Host "deleted $d" }
        }
        Write-Host 'Results gone; photos, truth.json and Label Studio kept. Start the tools again before the next run.'
    }
}

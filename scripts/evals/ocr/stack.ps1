# OCR evaluation stack (trial). Every tool runs on this PC with telemetry off; see docs/research/2026-10-25-ocr-eval-tools-trial.md.
#
#   scripts\evals\ocr\stack.ps1 up        Docker: Langfuse, Phoenix, Label Studio behind the gate (internal network)
#   scripts\evals\ocr\stack.ps1 mlflow    MLflow server on 127.0.0.1:19500 (background, .venv-eval)
#   scripts\evals\ocr\stack.ps1 fiftyone  FiftyOne app on 127.0.0.1:19151 (background, .venv-eval)
#   scripts\evals\ocr\stack.ps1 status    which ports answer
#   scripts\evals\ocr\stack.ps1 down      stop the containers (data volumes stay)
#
# Data and secrets live in the main checkout's gitignored cache\evals\ (stack.env is created on first `up`).
param([Parameter(Mandatory)][ValidateSet('up', 'down', 'mlflow', 'fiftyone', 'status')][string]$Action)
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

$compose = @('compose', '-f', (Join-Path $here 'docker-compose.yml'), '--env-file', $envFile)
switch ($Action) {
    'up' { Write-StackEnv; docker @compose up -d }
    'down' { docker @compose down }
    'mlflow' {
        $m = Join-Path $evals 'mlflow'
        New-Item -ItemType Directory -Force $m | Out-Null
        $db = 'sqlite:///' + ((Join-Path $m 'mlflow.db') -replace '\\', '/')
        Start-Process -WindowStyle Hidden -FilePath $py -ArgumentList @(
            '-m', 'mlflow', 'server', '--host', '127.0.0.1', '--port', '19500', '--workers', '1',
            '--backend-store-uri', $db, '--artifacts-destination', (Join-Path $m 'artifacts')) `
            -RedirectStandardOutput (Join-Path $evals 'logs\mlflow.out') -RedirectStandardError (Join-Path $evals 'logs\mlflow.err')
        Write-Host 'MLflow: http://127.0.0.1:19500'
    }
    'fiftyone' {
        Start-Process -WindowStyle Hidden -FilePath $py -ArgumentList @((Join-Path $here 'fo_app.py')) `
            -RedirectStandardOutput (Join-Path $evals 'logs\fiftyone.out') -RedirectStandardError (Join-Path $evals 'logs\fiftyone.err')
        Write-Host 'FiftyOne: http://127.0.0.1:19151'
    }
    'status' {
        foreach ($p in @(@('Langfuse', 19300), @('Langfuse MinIO', 19090), @('Phoenix', 19006), @('Label Studio', 19080),
                @('MLflow', 19500), @('FiftyOne', 19151))) {
            '{0,-15} {1,5}  {2}' -f $p[0], $p[1], $(if (Test-Port $p[1]) { 'up' } else { 'down' })
        }
    }
}

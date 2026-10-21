# 系统健康快照:摄像头流 / Frigate / 容器 / 近期错误
$ErrorActionPreference = 'SilentlyContinue'
$repo = Split-Path (Split-Path $PSScriptRoot -Parent) -Parent

Write-Output "===== 摄像头流(宿主 go2rtc :2984)====="
$s = curl.exe -s -m 5 http://127.0.0.1:2984/api/streams | ConvertFrom-Json
if ($null -eq $s) {
    Write-Output "  [X] 宿主 go2rtc 无响应 —— 先点【启动全部服务】"
} else {
    foreach ($name in $s.PSObject.Properties.Name) {
        $live = $s.$name.producers | Where-Object { $_.remote_addr }
        if ($live) {
            $mb = [math]::Round(($live | Measure-Object bytes_recv -Sum).Sum / 1MB, 1)
            $cons = @($s.$name.consumers).Count
            Write-Output "  [OK] $name  $($live[0].protocol)  $($live[0].remote_addr)  已收 ${mb}MB  观众 $cons"
        } else {
            Write-Output "  [--] $name  未连接(无人观看时属正常:go2rtc 是懒连接)"
        }
        # TD-25: 取一帧(静默,不推喇叭)。HTTP 200 但 0 字节 = P2P 生产者已死(常因米家 App 看过摄像头)
        $tmp = [IO.Path]::GetTempFileName()
        $code = curl.exe -s -m 15 -o $tmp -w "%{http_code}" "http://127.0.0.1:2984/api/frame.jpeg?src=$name"
        $size = (Get-Item $tmp).Length
        Remove-Item $tmp
        if ($code -eq "200" -and $size -gt 0) {
            Write-Output "       取帧 OK  $([math]::Round($size / 1KB))KB"
        } else {
            Write-Output "  [X]  $name  取帧失败(HTTP $code,$size 字节)—— 点【重启 go2rtc】(scripts\win\go2rtc-restart.bat);"
            Write-Output "       重启后仍失败:摄像头离线或 IP 变了(查 go2rtc-host.yaml 的地址,勿打印整个文件)"
        }
    }
}

Write-Output ""
Write-Output "===== 监督进程 supervisor(ADR-0016:所有服务自动恢复 + 告警)====="
$wt = Get-ScheduledTask -TaskName 'leafi-supervisor' -ErrorAction SilentlyContinue
if ($null -eq $wt) {
    Write-Output "  [--] 未安装登录任务(scripts\win\install-tasks.ps1);服务断了只能手动重启"
} else {
    Write-Output "  任务 leafi-supervisor: $($wt.State)"
}
Push-Location $repo
& .venv\Scripts\python.exe -m leafi alert --status 2>$null | ForEach-Object { "  $_" }
Pop-Location
foreach ($f in @("supervisor.log", "keep-supervisor.log")) {
    $p = Join-Path $repo "data\logs\$f"
    if (Test-Path $p) {
        Write-Output "  $f 最近 5 行:"
        Get-Content $p -Tail 5 | ForEach-Object { "    $_" }
    }
}

Write-Output ""
Write-Output "===== Frigate(:15000)====="
$st = curl.exe -s -m 5 http://127.0.0.1:15000/api/stats | ConvertFrom-Json
if ($null -eq $st) {
    Write-Output "  [X] Frigate 无响应"
} else {
    foreach ($cam in $st.cameras.PSObject.Properties.Name) {
        $c = $st.cameras.$cam
        $mark = if ($c.camera_fps -gt 0) { "OK" } else { "X " }
        Write-Output "  [$mark] $cam  收帧 $($c.camera_fps)fps  处理 $($c.process_fps)fps  丢帧 $($c.skipped_fps)"
    }
    if ($st.service.uptime) {
        Write-Output "  运行时长 $([math]::Round($st.service.uptime/3600,1)) 小时"
    }
}

Write-Output ""
Write-Output "===== 容器 ====="
Push-Location $repo
docker compose ps --format "  {{.Service}}  {{.Status}}"
Pop-Location

Write-Output ""
Write-Output "===== 宿主 go2rtc 近期日志 ====="
$log = Join-Path $repo "tools\go2rtc\host.log"
if (Test-Path $log) {
    $lines = Get-Content $log -Tail 2000
    $dials = @($lines | Select-String -SimpleMatch "xiaomi: dial").Count
    $errs = @($lines | Select-String -Pattern "ERR|WRN").Count
    Write-Output "  向小米云拨号取密钥: $dials 次(频繁增长=连接不稳)"
    Write-Output "  错误/警告行:       $errs"
    $displaced = @($lines | Select-String -SimpleMatch "unknown msg f1f00000").Count
    if ($displaced -gt 0) {
        Write-Output "  [X] P2P 会话被米家 App 挤掉 $displaced 次(cs2: unknown msg f1f00000)—— 点【重启 go2rtc】"
    }
    if ($errs -gt 0) {
        Write-Output "  最近 3 条:"
        $lines | Select-String -Pattern "ERR|WRN" | Select-Object -Last 3 |
            ForEach-Object { "    " + ($_.Line -replace 'C:/Users.*?go2rtc/', '') }
    }
} else {
    Write-Output "  (无日志文件,宿主 go2rtc 可能未启动过)"
}

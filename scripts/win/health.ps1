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
    $lines = Get-Content $log
    $dials = @($lines | Select-String -SimpleMatch "xiaomi: dial").Count
    $errs = @($lines | Select-String -Pattern "ERR|WRN").Count
    Write-Output "  向小米云拨号取密钥: $dials 次(频繁增长=连接不稳)"
    Write-Output "  错误/警告行:       $errs"
    if ($errs -gt 0) {
        Write-Output "  最近 3 条:"
        $lines | Select-String -Pattern "ERR|WRN" | Select-Object -Last 3 |
            ForEach-Object { "    " + ($_.Line -replace 'C:/Users.*?go2rtc/', '') }
    }
} else {
    Write-Output "  (无日志文件,宿主 go2rtc 可能未启动过)"
}

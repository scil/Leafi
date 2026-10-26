# Obsidian console entry point for this project (obsidian-console skill): every console button runs
# this one file with a key, and each key runs one fixed command; an unknown key runs nothing.
# Shell commands: "Leafi 控制台" runs it with {{_console_button}} as -Button, "Leafi 控制台(先确认)" does the
# same after asking; buttons that read the editor or prompt for values have their own command with a fixed key.
param(
    [Parameter(Mandatory = $true)][string]$Button,
    [string]$Selection = ''
)
$ErrorActionPreference = 'Stop'
Set-Location (Split-Path -Parent (Split-Path -Parent $PSScriptRoot))

function Done([int[]]$Ok = @()) {
    $code = if ($null -eq $LASTEXITCODE) { 0 } else { $LASTEXITCODE }
    if ($Ok -contains $code) { $code = 0 }
    exit $code
}

switch ($Button) {
    'up' { cmd /c "cd /d E:\GitHub\scil\Leafi && scripts\win\up.bat < nul"; Done }  # 启动全部服务
    'health' { cmd /c "cd /d E:\GitHub\scil\Leafi && scripts\win\health.bat < nul"; Done }  # 系统健康检查
    'go2rtc-restart' { cmd /c "cd /d E:\GitHub\scil\Leafi && scripts\win\go2rtc-restart.bat < nul"; Done }  # 重启 go2rtc
    'uninstall-tasks' { cmd /c "cd /d E:\GitHub\scil\Leafi && scripts\win\uninstall-tasks.bat < nul"; Done }  # 卸载守护任务
    'install-tasks' { cmd /c "cd /d E:\GitHub\scil\Leafi && scripts\win\install-tasks.bat < nul"; Done }  # 安装守护任务
    'alerts-drain' { cmd /c "cd /d E:\GitHub\scil\Leafi && scripts\win\alerts-drain.bat < nul"; Done }  # 补发告警
    'toast-test' { cmd /c "cd /d E:\GitHub\scil\Leafi && scripts\win\toast-test.bat < nul"; Done }  # 测试弹窗
    'supervisor-timing' { cmd /c "cd /d E:\GitHub\scil\Leafi && scripts\win\supervisor-timing.bat < nul"; Done @(1) }  # 守护时间设置
    'supervisor-status' { cmd /c "cd /d E:\GitHub\scil\Leafi && scripts\win\supervisor-status.bat < nul"; Done }  # 守护状态
    'checks' { cmd /c "cd /d E:\GitHub\scil\Leafi && scripts\win\checks.bat < nul"; Done @(1) }  # 配置检查
    'apply-env' { cmd /c "cd /d E:\GitHub\scil\Leafi && scripts\win\apply-env.bat < nul"; Done }  # 应用 .env 并重启 Frigate
    'logs' { cmd /c "cd /d E:\GitHub\scil\Leafi && scripts\win\logs-tail.bat < nul"; Done }  # 看最近日志
    'down' { cmd /c "cd /d E:\GitHub\scil\Leafi && scripts\win\down.bat < nul"; Done }  # 停止全部服务
    'edit-env' { cmd /c "cd /d E:\GitHub\scil\Leafi && scripts\win\edit-env.bat < nul"; Done }  # 编辑 .env
    'backup' { cmd /c "cd /d E:\GitHub\scil\Leafi && scripts\win\backup.bat < nul"; Done }  # 备份数据库
    'migrate' { powershell -NoProfile -ExecutionPolicy Bypass -File scripts\win\migrate.ps1; Done }  # 迁移数据库
    'backup-prune' { cmd /c "cd /d E:\GitHub\scil\Leafi && scripts\win\backup-prune.bat < nul"; Done }  # 清除旧备份
    'mock' { cmd /c "cd /d E:\GitHub\scil\Leafi && scripts\win\mock-run.bat < nul"; Done }  # Mock 联调(不出声)
    'say' { cmd /c "cd /d E:\GitHub\scil\Leafi && scripts\win\say-test.bat < nul"; Done }  # 真机试喇叭(会出声)
    'test' { cmd /c "cd /d E:\GitHub\scil\Leafi && scripts\win\test.bat < nul"; Done }  # 跑单测
    'say-selection' { .venv\Scripts\python.exe -m agent.main --say $Selection; Done }  # 念选中的文字
    'say-paragraph' { .venv\Scripts\python.exe -m agent.main --say $Selection; Done }  # 念光标所在行
    'taskeditor' { cmd /c start "Leafi 动作与设置" /d E:\GitHub\scil\Leafi .venv\Scripts\python.exe -m agent.webui; Done }  # 动作编辑界面
    'eval-download' { cmd /c "cd /d E:\GitHub\scil\Leafi && scripts\win\eval-data-download.bat < nul"; Done }  # 下载评测数据
    'reading-eval' { cmd /c "cd /d E:\GitHub\scil\Leafi && scripts\win\reading-eval.bat < nul"; Done }  # 朗读评测
    'privacy-setup' { .venv\Scripts\python.exe -m leafi setup; Done }  # 隐私设置步骤
    'privacy-schools' { .venv\Scripts\python.exe -m leafi privacy schools; Done }  # 孩子的学校
    'privacy-terms' { .venv\Scripts\python.exe -m leafi privacy terms; Done }  # 受保护的名字
    'study-pc' { cmd /c start "Leafi 读书 (PC 喇叭)" /d E:\GitHub\scil\Leafi cmd /k .venv\Scripts\python.exe -m leafi study --mouth pc; Done }  # 开始读书(PC 喇叭)
    'study-camera' { cmd /c start "Leafi 读书 (摄像头喇叭)" /d E:\GitHub\scil\Leafi cmd /k .venv\Scripts\python.exe -m leafi study; Done }  # 开始读书(摄像头喇叭)
    'study-pc-panel' { cmd /c start "Leafi 读书 (PC 喇叭, 面板)" /d E:\GitHub\scil\Leafi cmd /k .venv\Scripts\python.exe -m leafi study --mouth pc --panel; Done }  # Start reading (PC speaker) with the session panel
    'study-panel' { cmd /c start "Leafi 动作与设置" /d E:\GitHub\scil\Leafi .venv\Scripts\python.exe -m agent.webui --tab read; Done }  # Session panel: the web UI's Reading tab
    'brain-probe' { .venv\Scripts\python.exe scripts\probes\brain_compile.py; Done }  # Brain 连通测试
    'check-snapshot' { .venv\Scripts\python.exe scripts\probes\checks.py snapshot; Done }  # 摄像头截图
    'check-ocr' { .venv\Scripts\python.exe scripts\probes\checks.py ocr; Done @(1) }  # OCR(新拍)
    'check-ocr-last' { .venv\Scripts\python.exe scripts\probes\checks.py ocr-last; Done @(1) }  # OCR(最新截图)
    'ocr-review' { cmd /c start "Leafi 动作与设置" /d E:\GitHub\scil\Leafi .venv\Scripts\python.exe -m agent.webui --tab ocr; Done }  # OCR 识别成果(网页)
    'eval-start' { pwsh -NoProfile -File scripts\evals\ocr\stack.ps1 start; Done }  # 启动评测工具
    'eval-stop' { pwsh -NoProfile -File scripts\evals\ocr\stack.ps1 stop; Done }  # 停止评测工具
    'eval-status' { pwsh -NoProfile -File scripts\evals\ocr\stack.ps1 status; Done }  # 评测工具状态
    'eval-add-snapshot' { pwsh -NoProfile -File scripts\evals\ocr\stack.ps1 add-snapshot; Done }  # 最新截图加入评测集
    'eval-labels-push' { pwsh -NoProfile -File scripts\evals\ocr\stack.ps1 labels-push; Done }  # 照片同步到 Label Studio
    'eval-labels-pull' { pwsh -NoProfile -File scripts\evals\ocr\stack.ps1 labels-pull; Done }  # 取回标注
    'eval-run-default' { pwsh -NoProfile -File scripts\evals\ocr\stack.ps1 run -Pipeline default; Done }  # OCR 评测(默认)
    'eval-run-probe-k2' { pwsh -NoProfile -File scripts\evals\ocr\stack.ps1 run -Pipeline probe-k2; Done }  # OCR 评测(probe-k2)
    'eval-run-scan-only' { pwsh -NoProfile -File scripts\evals\ocr\stack.ps1 run -Pipeline scan-only; Done }  # OCR 评测(scan-only)
    'eval-netwatch' { pwsh -NoProfile -File scripts\evals\ocr\netwatch.ps1 -Seconds 60 -Control; Done }  # 出站流量检查
    'check-mic' { .venv\Scripts\python.exe scripts\probes\checks.py mic; Done @(1) }  # 麦克风测试
    'check-tts' { .venv\Scripts\python.exe scripts\probes\checks.py tts; Done }  # 语音合成测试
    'check-speaker' { .venv\Scripts\python.exe scripts\probes\checks.py speaker; Done }  # PC 喇叭试音
    default { Write-Output "Unknown console button: $Button"; exit 2 }
}

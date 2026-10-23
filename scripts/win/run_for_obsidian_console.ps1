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
    'backup-prune' { cmd /c "cd /d E:\GitHub\scil\Leafi && scripts\win\backup-prune.bat < nul"; Done }  # 清除旧备份
    'mock' { cmd /c "cd /d E:\GitHub\scil\Leafi && scripts\win\mock-run.bat < nul"; Done }  # Mock 联调(不出声)
    'say' { cmd /c "cd /d E:\GitHub\scil\Leafi && scripts\win\say-test.bat < nul"; Done }  # 真机试喇叭(会出声)
    'test' { cmd /c "cd /d E:\GitHub\scil\Leafi && scripts\win\test.bat < nul"; Done }  # 跑单测
    'say-selection' { .venv\Scripts\python.exe -m agent.main --say $Selection; Done }  # 念选中的文字
    'say-paragraph' { .venv\Scripts\python.exe -m agent.main --say $Selection; Done }  # 念光标所在行
    'taskeditor' { cmd /c start "Leafi 动作与设置" /d E:\GitHub\scil\Leafi .venv\Scripts\python.exe -m agent.webui; Done }  # 动作编辑界面
    'eval-download' { cmd /c "cd /d E:\GitHub\scil\Leafi && scripts\win\eval-data-download.bat < nul"; Done }  # 下载评测数据
    'reading-eval' { cmd /c "cd /d E:\GitHub\scil\Leafi && scripts\win\reading-eval.bat < nul"; Done }  # 朗读评测
    default { Write-Output "Unknown console button: $Button"; exit 2 }
}

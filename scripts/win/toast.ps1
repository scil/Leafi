# Windows toast for Leafi alerts (ADR-0016). Must run under Windows PowerShell 5.1 (powershell.exe):
# PowerShell 7 cannot load the WinRT notification types. Called by leafi/ops/alerts.py::windows_toast.
param([string]$Title = "Leafi", [string]$Body = "")
[Windows.UI.Notifications.ToastNotificationManager, Windows.UI.Notifications, ContentType = WindowsRuntime] | Out-Null
[Windows.Data.Xml.Dom.XmlDocument, Windows.Data.Xml.Dom.XmlDocument, ContentType = WindowsRuntime] | Out-Null
$esc = [Security.SecurityElement]
$xml = New-Object Windows.Data.Xml.Dom.XmlDocument
$xml.LoadXml("<toast><visual><binding template='ToastGeneric'><text>$($esc::Escape($Title))</text><text>$($esc::Escape($Body))</text></binding></visual></toast>")
# PowerShell's own AppUserModelID: toasts appear under "Windows PowerShell" in the notification center.
$appId = '{1AC14E77-02E7-4E5D-B744-2EB1AE5198B7}\WindowsPowerShell\v1.0\powershell.exe'
[Windows.UI.Notifications.ToastNotificationManager]::CreateToastNotifier($appId).Show([Windows.UI.Notifications.ToastNotification]::new($xml))

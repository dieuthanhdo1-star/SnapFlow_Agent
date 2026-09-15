[Console]::OutputEncoding = New-Object System.Text.UTF8Encoding($false)
Add-Type -AssemblyName System.Windows.Forms
$picker = New-Object System.Windows.Forms.FolderBrowserDialog
$picker.Description = '选择需要 SnapFlow 自动整理的截图文件夹（不读取子文件夹）'
$picker.ShowNewFolderButton = $false
$owner = New-Object System.Windows.Forms.Form
$owner.TopMost = $true
$owner.ShowInTaskbar = $false
$owner.Opacity = 0
$owner.Show()
try {
    if ($picker.ShowDialog($owner) -eq [System.Windows.Forms.DialogResult]::OK) {
        @{path = $picker.SelectedPath} | ConvertTo-Json -Compress
    } else { @{path = ''} | ConvertTo-Json -Compress }
} finally { $picker.Dispose(); $owner.Dispose() }

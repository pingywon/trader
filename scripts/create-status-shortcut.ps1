# Regenerates the "Insider Tracker Status" shortcut on your Desktop with
# paths resolved for the current user and the current clone of this repo.
#
# Usage:  powershell -ExecutionPolicy Bypass -File scripts\create-status-shortcut.ps1

$ErrorActionPreference = 'Stop'

# Resolve the repo root as the parent of this script's directory
$repoRoot = (Resolve-Path (Join-Path $PSScriptRoot '..')).Path
$desktop  = [Environment]::GetFolderPath('Desktop')
$lnkPath  = Join-Path $desktop 'Insider Tracker Status.lnk'

$ws  = New-Object -ComObject WScript.Shell
$lnk = $ws.CreateShortcut($lnkPath)
$lnk.TargetPath       = 'C:\Windows\System32\cmd.exe'
$lnk.Arguments        = '/k uv run insider-tracker status'
$lnk.WorkingDirectory = $repoRoot
$lnk.IconLocation     = 'C:\Windows\System32\cmd.exe,0'
$lnk.Description      = 'Show last insider-tracker filings and trades'
$lnk.Save()

Write-Host "Shortcut created: $lnkPath"
Write-Host "Working directory: $repoRoot"
Write-Host ""
Write-Host "To pin: right-click the Desktop shortcut -> Show more options -> Pin to taskbar."

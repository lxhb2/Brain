<#
.SYNOPSIS
Register the brain.local publisher as the current user's logon task.

.USAGE
Run from an elevated PowerShell session:
  powershell.exe -NoProfile -ExecutionPolicy Bypass ^
    -File .\scripts\register-brain-mdns.ps1
#>

$ErrorActionPreference = 'Stop'

$python = Join-Path (Split-Path (Get-Command python.exe).Source) 'pythonw.exe'
$script = Join-Path $PSScriptRoot 'brain-mdns.py'

if (-not (Test-Path -LiteralPath $python)) {
    throw "pythonw.exe was not found: $python"
}
if (-not (Test-Path -LiteralPath $script)) {
    throw "brain-mdns.py was not found: $script"
}

$action = New-ScheduledTaskAction -Execute $python -Argument ('"{0}"' -f $script)
$trigger = New-ScheduledTaskTrigger -AtLogOn -User "$env:USERDOMAIN\$env:USERNAME"
$settings = New-ScheduledTaskSettingsSet `
    -AllowStartIfOnBatteries `
    -DontStopIfGoingOnBatteries `
    -StartWhenAvailable `
    -RestartCount 3 `
    -RestartInterval (New-TimeSpan -Minutes 1) `
    -ExecutionTimeLimit ([TimeSpan]::Zero)

Register-ScheduledTask `
    -TaskName 'Brain mDNS Alias' `
    -Action $action `
    -Trigger $trigger `
    -Settings $settings `
    -Force | Out-Null

Write-Host "[INFO] Registered scheduled task: Brain mDNS Alias" -ForegroundColor Green

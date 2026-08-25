#Requires -RunAsAdministrator

<#
.SYNOPSIS
Refresh Windows-to-WSL2 portproxy rules for Brain.

.DESCRIPTION
WSL2 uses a NAT address that can change after Windows or WSL restarts.
This script reads the current WSL IPv4 address and refreshes the portproxy
rules used by Brain. It also creates inbound firewall rules.

.USAGE
powershell.exe -NoProfile -ExecutionPolicy Bypass ^
  -File .\scripts\fix-wsl-portproxy.ps1

To register a current-user logon task:
powershell.exe -NoProfile -ExecutionPolicy Bypass ^
  -File .\scripts\fix-wsl-portproxy.ps1 -RegisterTask
#>

[CmdletBinding()]
param(
    [int[]]$Ports = @(8080, 8000, 8384, 22000, 21027, 8090),
    [string]$WslDistro,
    [switch]$RegisterTask,
    [string]$TaskName = 'Brain WSL PortProxy Refresh',
    [int]$WaitSeconds = 60
)

$ErrorActionPreference = 'Stop'

function Write-Info($message) { Write-Host "[INFO] $message" -ForegroundColor Green }
function Write-Warn2($message) { Write-Host "[WARN] $message" -ForegroundColor Yellow }

if (-not (Get-Command wsl.exe -ErrorAction SilentlyContinue)) {
    throw 'wsl.exe was not found. Install WSL first.'
}

$distroArgs = @()
if ($WslDistro) {
    $distros = wsl.exe --list --quiet | ForEach-Object { ($_ -replace "`0", '').Trim() } | Where-Object { $_ }
    if ($WslDistro -notin $distros) {
        throw "WSL distro not found: $WslDistro. Available: $($distros -join ', ')"
    }
    $distroArgs = @('--distribution', $WslDistro)
}

$deadline = (Get-Date).AddSeconds($WaitSeconds)
$wslIp = $null

while (-not $wslIp -and (Get-Date) -lt $deadline) {
    try {
        $rawAddress = & wsl.exe @distroArgs hostname -I 2>$null
        $wslIp = (($rawAddress -join ' ') -replace "`0", '').Trim() -split '\s+' |
            Where-Object { $_ -match '^(\d{1,3}\.){3}\d{1,3}$' } |
            Select-Object -First 1
    } catch {
        Write-Warn2 "Waiting for WSL: $($_.Exception.Message)"
    }

    if (-not $wslIp) {
        Start-Sleep -Seconds 2
    }
}

if (-not $wslIp) {
    throw "Could not read a WSL IPv4 address after $WaitSeconds seconds."
}

Write-Info "Current WSL IPv4 address: $wslIp"

foreach ($port in $Ports) {
    $output = netsh interface portproxy show v4tov4
    $rulesToRemove = @($output | Select-String -Pattern ('^\s*' + [regex]::Escape([string]$port) + '\s+') |
        ForEach-Object { $_.Line })

    foreach ($line in $rulesToRemove) {
        $parts = @(($line -split '\s+') | Where-Object { $_ })
        if ($parts.Count -ge 4) {
            netsh interface portproxy delete v4tov4 `
                listenaddress=$($parts[0]) listenport=$($parts[1]) | Out-Null
        }
    }

    netsh interface portproxy add v4tov4 `
        listenaddress=0.0.0.0 listenport=$port connectaddress=$wslIp connectport=$port | Out-Null

    Write-Info "Port proxy ready: Windows :$port -> WSL ${wslIp}:$port"
}

# Rules are generated from the same port list. UDP is needed by Syncthing discovery/transfer.
foreach ($port in $Ports) {
    foreach ($protocol in @('TCP', 'UDP')) {
        $ruleName = "Brain $protocol $port"
        if (-not (Get-NetFirewallRule -DisplayName $ruleName -ErrorAction SilentlyContinue)) {
            New-NetFirewallRule -DisplayName $ruleName -Direction Inbound `
                -Protocol $protocol -LocalPort $port -Action Allow | Out-Null
        }
    }
}

Write-Info 'Firewall rules are ready.'

if ($RegisterTask) {
    $scriptFullPath = $PSCommandPath
    $action = New-ScheduledTaskAction -Execute 'powershell.exe' -Argument `
        "-NoProfile -ExecutionPolicy Bypass -WindowStyle Hidden -File `"$scriptFullPath`""
    $logonTrigger = New-ScheduledTaskTrigger -AtLogOn -User $env:USERDOMAIN\$env:USERNAME
    $startupTrigger = New-ScheduledTaskTrigger -AtStartup
    $principal = New-ScheduledTaskPrincipal -UserId "$env:USERDOMAIN\$env:USERNAME" `
        -LogonType Interactive -RunLevel Highest
    $settings = New-ScheduledTaskSettingsSet `
        -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries -StartWhenAvailable `
        -RestartCount 3 -RestartInterval (New-TimeSpan -Minutes 1)

    Register-ScheduledTask -TaskName $TaskName -Action $action `
        -Trigger @($startupTrigger, $logonTrigger) `
        -Principal $principal -Settings $settings -Force | Out-Null

    Write-Info "Scheduled task registered: $TaskName"
}

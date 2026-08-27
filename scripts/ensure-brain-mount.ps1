param(
    [string]$DistroName = "Ubuntu-22.04",
    [string]$ProjectDir = "/home/lxhb/brain",
    [string]$DataDir = "/home/lxhb/.local/var/brain"
)

$ErrorActionPreference = "Stop"

function Invoke-Wsl {
    param([string]$Command)

    & wsl.exe -d $DistroName --cd $ProjectDir -- bash -lc $Command
    return $LASTEXITCODE
}

function Wait-BrainHealth {
    for ($i = 0; $i -lt 30; $i++) {
        try {
            Invoke-RestMethod -Uri "http://127.0.0.1:8000/api/health" -TimeoutSec 2 | Out-Null
            return $true
        } catch {
            Start-Sleep -Seconds 2
        }
    }
    return $false
}

function Get-ContainerToken {
    param([string]$ProbeName)

    $value = ""
    try {
        $out = & wsl.exe -d $DistroName -- docker exec brain-backend cat "/app/data/$ProbeName" 2>$null
        if ($LASTEXITCODE -eq 0) {
            $value = (@($out) -join "").Trim()
        }
    } catch {
        $value = ""
    }
    return $value
}

function Repair-DataContainers {
    & wsl.exe -d $DistroName --cd $ProjectDir -- docker compose --profile sync up -d --force-recreate backend cloud syncthing
    return $LASTEXITCODE
}

# Docker Desktop may still be starting when this runs at logon. Give the daemon
# a short window before deciding that a mount is detached.
$dockerReady = $false
for ($i = 0; $i -lt 30; $i++) {
    & wsl.exe -d $DistroName -- docker info 2>$null | Out-Null
    if ($LASTEXITCODE -eq 0) {
        $dockerReady = $true
        break
    }
    Start-Sleep -Seconds 2
}
if (-not $dockerReady) {
    throw "Docker daemon did not become ready in $DistroName. Check Docker Desktop and WSL."
}

# Write a fresh token on the WSL filesystem, then read it through the backend
# container. If Docker/WSL restart leaves the bind mount empty or detached,
# the token will not match and the affected services can be recreated safely.
$probeName = ".brain-mount-probe"
$token = [guid]::NewGuid().ToString("N")
$escapedDataDir = $DataDir.Replace("'", "'\''")
$writeCode = "mkdir -p '$escapedDataDir' && printf '%s' '$token' > '$escapedDataDir/$probeName'"

if ((Invoke-Wsl $writeCode) -ne 0) {
    throw "Unable to create mount probe in $DistroName`:$DataDir"
}

$containerToken = Get-ContainerToken -ProbeName $probeName
if ($containerToken -eq $token) {
    Write-Host "Brain data mount is healthy."
    exit 0
}

$repaired = $false
for ($attempt = 1; $attempt -le 6; $attempt++) {
    Write-Warning "Brain data mount is detached or empty. Recreating Brain services (attempt $attempt/6)..."
    if ((Repair-DataContainers) -ne 0) {
        Write-Warning "Docker Compose recreate failed; waiting before retrying..."
    } elseif (Wait-BrainHealth) {
        $containerToken = Get-ContainerToken -ProbeName $probeName
        if ($containerToken -eq $token) {
            $repaired = $true
            break
        }
        Write-Warning "Backend is healthy but cannot see $DataDir yet; waiting for Docker Desktop mount service..."
    }
    Start-Sleep -Seconds 10
}

if (-not $repaired) {
    throw "Brain data mount is still detached after 6 attempts. Check Docker Desktop, WSL and $DataDir."
}

Write-Host "Brain data mount repaired successfully."

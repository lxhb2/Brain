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

$containerToken = ""
try {
    $result = & wsl.exe -d $DistroName -- docker exec brain-backend cat "/app/data/$probeName" 2>$null
    if ($LASTEXITCODE -eq 0) {
        $containerToken = (@($result) -join "").Trim()
    }
} catch {
    $containerToken = ""
}

if ($containerToken -eq $token) {
    Write-Host "Brain data mount is healthy."
    exit 0
}

Write-Warning "Brain data mount is detached or empty. Recreating Brain services..."
& wsl.exe -d $DistroName --cd $ProjectDir -- docker compose --profile sync up -d --force-recreate backend cloud syncthing
if ($LASTEXITCODE -ne 0) {
    throw "Failed to recreate Brain services."
}

if (-not (Wait-BrainHealth)) {
    throw "Brain backend did not become healthy after remounting."
}

$result = & wsl.exe -d $DistroName -- docker exec brain-backend cat "/app/data/$probeName" 2>$null
$containerToken = (@($result) -join "").Trim()
if ($containerToken -ne $token) {
    throw "Backend is healthy but still cannot see $DataDir. Check Docker Desktop and WSL."
}

Write-Host "Brain data mount repaired successfully."

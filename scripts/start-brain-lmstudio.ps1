$ErrorActionPreference = "Continue"

# Ensure the virtualized server stack is actually running before repairing mounts.
if (-not (Get-Process "Docker Desktop" -ErrorAction SilentlyContinue)) {
    $dockerDesktop = Join-Path $env:ProgramFiles "Docker\Docker\Docker Desktop.exe"
    if (-not (Test-Path -LiteralPath $dockerDesktop)) {
        Write-Warning "Docker Desktop was not found at: $dockerDesktop"
    } else {
        Write-Host "Starting Docker Desktop..."
        Start-Process -FilePath $dockerDesktop -WindowStyle Hidden
        Start-Sleep -Seconds 5
    }
}

# Docker Desktop/WSL restarts can occasionally detach bind mounts. Repair that
# before models are loaded so existing notes and cloud files remain visible.
$ensureMount = Join-Path $PSScriptRoot "ensure-brain-mount.ps1"
if (Test-Path -LiteralPath $ensureMount) {
    & powershell.exe -NoProfile -ExecutionPolicy Bypass -File $ensureMount
}

$lms = Join-Path $env:USERPROFILE ".lmstudio\bin\lms.exe"
if (-not (Test-Path -LiteralPath $lms)) {
    Write-Warning "LM Studio CLI not found: $lms"
    exit 1
}

try {
    Invoke-RestMethod -Uri "http://127.0.0.1:1234/v1/models" -TimeoutSec 2 | Out-Null
} catch {
    & $lms server start --port 1234 | Out-Null
}

for ($i = 0; $i -lt 20; $i++) {
    try {
        Invoke-RestMethod -Uri "http://127.0.0.1:1234/v1/models" -TimeoutSec 2 | Out-Null
        break
    } catch {
        Start-Sleep -Seconds 1
    }
}

try {
    $loaded = ((Invoke-RestMethod -Uri "http://127.0.0.1:1234/v1/models" -TimeoutSec 5).data |
        ForEach-Object { $_.id }) -join "`n"
} catch {
    $loaded = ""
}
if ($loaded -notmatch "qwen3\.5-4b") {
    & $lms load qwen3.5-4b --identifier qwen3.5-4b --ttl 31536000 -y
}

if ($loaded -notmatch "text-embedding-nomic-embed-text-v1\.5") {
    & $lms load text-embedding-nomic-embed-text-v1.5 `
        --identifier text-embedding-nomic-embed-text-v1.5 `
        --ttl 31536000 -y
}

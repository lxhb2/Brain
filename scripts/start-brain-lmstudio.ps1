$ErrorActionPreference = "Continue"

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

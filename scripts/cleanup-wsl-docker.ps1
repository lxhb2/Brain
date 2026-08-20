<#
.SYNOPSIS
  Docker WSL vhdx 清理脚本 —— 释放被动态扩展占用但未归还的磁盘空间
.DESCRIPTION
  1. 清理 Docker 内部垃圾（悬挂镜像/停止容器/构建缓存/未使用卷）
  2. 关闭 Docker Desktop + WSL
  3. 用 diskpart compact 压缩 ext4.vhdx
  4. 报告释放前后大小
.NOTES
  需要以管理员身份运行 PowerShell
  执行策略：Set-ExecutionPolicy -Scope CurrentUser RemoteSigned
#>

#Requires -RunAsAdministrator

$ErrorActionPreference = "Stop"

function Write-Step($msg) { Write-Host "`n[步骤] $msg" -ForegroundColor Cyan }
function Write-Ok($msg)   { Write-Host "  [OK] $msg" -ForegroundColor Green }
function Write-Warn($msg) { Write-Host "  [!]  $msg" -ForegroundColor Yellow }
function Write-Err($msg)  { Write-Host "  [X]  $msg" -ForegroundColor Red }

# ---------- 1. 清理 Docker 内部 ----------
Write-Step "1/5 清理 Docker 内部垃圾"

$dockerRunning = Get-Process "Docker Desktop" -ErrorAction SilentlyContinue
if (-not $dockerRunning) {
    Write-Warn "Docker Desktop 未运行，跳过 Docker 内部清理"
} else {
    # 通过 wsl 调 docker 命令（Docker Desktop 运行时 wsl 里可直接用 docker）
    $wslDocker = wsl -e docker system df 2>$null
    if ($wslDocker) {
        Write-Host "  清理前占用："
        Write-Host ($wslDocker | ForEach-Object { "    $_" })
        Write-Host ""
        wsl -e docker system prune -a -f --volumes 2>&1 | ForEach-Object { Write-Host "    $_" }
        wsl -e docker builder prune -a -f 2>&1 | ForEach-Object { Write-Host "    $_" }
        Write-Ok "Docker 内部清理完成"
    } else {
        Write-Warn "无法通过 WSL 调用 docker，尝试 Docker Desktop CLI"
        $dockerCli = Get-Command docker -ErrorAction SilentlyContinue
        if ($dockerCli) {
            docker system prune -a -f --volumes 2>&1 | ForEach-Object { Write-Host "    $_" }
            docker builder prune -a -f 2>&1 | ForEach-Object { Write-Host "    $_" }
            Write-Ok "Docker 内部清理完成（CLI）"
        } else {
            Write-Warn "找不到 docker CLI，跳过"
        }
    }
}

# ---------- 2. 查找 vhdx 文件 ----------
Write-Step "2/5 查找 vhdx 文件"

$vhdxFiles = @()
$searchPaths = @(
    "$env:LOCALAPPDATA\Docker\wsl",
    "$env:LOCALAPPDATA\Docker\wsl\data",
    "$env:LOCALAPPDATA\Docker\wsl\disk",
    "$env:PROGRAMDATA\DockerDesktop"
)

foreach ($p in $searchPaths) {
    if (Test-Path $p) {
        $found = Get-ChildItem -Path $p -Filter "*.vhdx" -Recurse -ErrorAction SilentlyContinue
        if ($found) { $vhdxFiles += $found }
    }
}

if ($vhdxFiles.Count -eq 0) {
    Write-Warn "未在默认路径找到 vhdx，尝试全盘搜索（可能较慢）..."
    $drives = Get-PSDrive -PSProvider FileSystem | Where-Object { $_.Used -gt 0 }
    foreach ($d in $drives) {
        $root = "$($d.Name):\"
        # 只搜 Docker 相关目录
        $dockerDirs = Get-ChildItem -Path $root -Directory -ErrorAction SilentlyContinue |
                      Where-Object { $_.Name -match "Docker|wsl" }
        foreach ($dd in $dockerDirs) {
            $found = Get-ChildItem -Path $dd.FullName -Filter "*.vhdx" -Recurse -ErrorAction SilentlyContinue
            if ($found) { $vhdxFiles += $found }
        }
    }
}

if ($vhdxFiles.Count -eq 0) {
    Write-Err "未找到任何 vhdx 文件，退出"
    exit 1
}

# 去重
$vhdxFiles = $vhdxFiles | Sort-Object FullName -Unique
Write-Ok "找到 $($vhdxFiles.Count) 个 vhdx 文件："
foreach ($f in $vhdxFiles) {
    $sizeMB = [math]::Round($f.Length / 1MB, 1)
    Write-Host "    $($f.FullName)  ($sizeMB MB)"
}

# ---------- 3. 关闭 Docker Desktop + WSL ----------
Write-Step "3/5 关闭 Docker Desktop + WSL"

$dd = Get-Process "Docker Desktop" -ErrorAction SilentlyContinue
if ($dd) {
    Write-Host "  正在关闭 Docker Desktop..."
    Stop-Process -Name "Docker Desktop" -Force -ErrorAction SilentlyContinue
    # 杀掉相关子进程
    Stop-Process -Name "com.docker.backend" -Force -ErrorAction SilentlyContinue
    Stop-Process -Name "com.docker.service" -Force -ErrorAction SilentlyContinue
    Start-Sleep -Seconds 5
    Write-Ok "Docker Desktop 已关闭"
} else {
    Write-Warn "Docker Desktop 未运行"
}

Write-Host "  正在关闭 WSL..."
wsl --shutdown 2>&1 | Out-Null
Start-Sleep -Seconds 8  # 等待 WSL 完全释放文件锁
Write-Ok "WSL 已关闭"

# ---------- 4. 压缩 vhdx ----------
Write-Step "4/5 压缩 vhdx（diskpart compact）"

$totalBefore = 0
$totalAfter = 0

foreach ($vhdx in $vhdxFiles) {
    $path = $vhdx.FullName
    $beforeMB = [math]::Round($vhdx.Length / 1MB, 1)
    $totalBefore += $beforeMB
    Write-Host "`n  压缩: $path ($beforeMB MB)"

    # diskpart 脚本
    $script = @"
select vdisk file="$path"
attach vdisk readonly
compact vdisk
detach vdisk
exit
"@
    $scriptFile = [System.IO.Path]::GetTempFileName()
    $script | Out-File -FilePath $scriptFile -Encoding ASCII

    try {
        $output = diskpart /s $scriptFile 2>&1
        $output | ForEach-Object { Write-Host "    $_" -ForegroundColor DarkGray }

        # 重新读取文件大小
        $after = Get-Item $path
        $afterMB = [math]::Round($after.Length / 1MB, 1)
        $totalAfter += $afterMB
        $saved = [math]::Round($beforeMB - $afterMB, 1)
        if ($saved -gt 0) {
            Write-Ok "压缩成功: $beforeMB MB -> $afterMB MB  (释放 $saved MB)"
        } else {
            Write-Warn "未释放空间: $beforeMB MB -> $afterMB MB (vhdx 已经是紧凑的)"
        }
    } catch {
        Write-Err "压缩失败: $_"
    } finally {
        Remove-Item $scriptFile -ErrorAction SilentlyContinue
    }
}

# ---------- 5. 汇总 ----------
Write-Step "5/5 完成"
$totalSaved = [math]::Round($totalBefore - $totalAfter, 1)
Write-Host ""
Write-Host "  压缩前总计: $totalBefore MB" -ForegroundColor White
Write-Host "  压缩后总计: $totalAfter MB" -ForegroundColor White
Write-Host "  释放空间:   $totalSaved MB" -ForegroundColor Green
Write-Host ""
Write-Host "  提示: 现在可以重新启动 Docker Desktop" -ForegroundColor Cyan
Write-Host ""

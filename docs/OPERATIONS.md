# Brain 私有云盘与 WSL 运维手册

本文档对应当前已经部署在本机 WSL 的 Brain 服务，包含稳定存储、私有云盘、备份、恢复、换 IP 后访问和常见故障处理。

## 当前部署位置

| 项目 | 位置 |
| --- | --- |
| Windows 本地代码 | `F:\桌面\Brain` |
| WSL 运行目录 | `/home/lxhb/brain` |
| 稳定数据目录 | `/home/lxhb/.local/var/brain` |
| 实际磁盘文件 | `G:\WSL\Ubuntu-22.04\ext4.vhdx` |
| 云盘文件根目录 | `/home/lxhb/.local/var/brain/cloud` |
| 云盘账号数据库 | `/home/lxhb/.local/var/brain/sftpgo/config/sftpgo.db` |
| 数据库备份目录 | `/home/lxhb/.local/var/brain/backups` |

数据写在 WSL 的 Linux 文件系统里；因为 Ubuntu-22.04 的 `ext4.vhdx` 放在 `G:\WSL\Ubuntu-22.04\`，所以数据实际保存在 G 盘。Windows 物理机 IP 变化不会影响这些路径。不要把 `BRAIN_DATA_DIR` 改成 `/mnt/g/...`，9p 挂载在权限、性能和数据库一致性上都不可靠。

## 服务地址

本机访问：

```text
Brain 前端：       http://127.0.0.1:8080
手机连接助手：     http://127.0.0.1:8080/connect
Brain API 健康：   http://127.0.0.1:8000/api/health
私有云盘客户端：   http://127.0.0.1:8090/web/client
私有云盘管理端：   http://127.0.0.1:8090/web/admin
Syncthing 管理：   http://127.0.0.1:8384
```

局域网和手机优先使用固定名 `brain.local`：

```text
http://brain.local:8080
http://brain.local:8080/connect
http://brain.local:8000/api/health
http://brain.local:8090/web/client
```

如果某台设备不支持 mDNS，再把 `127.0.0.1` 换成物理机的局域网 IP，例如：

```text
http://172.29.32.54:8080
http://172.29.32.54:8090/web/client
```

IP 可用 PowerShell 查看：

```powershell
Get-NetIPConfiguration | Where-Object { $_.IPv4Address } |
  Select-Object InterfaceAlias, @{n='IPv4';e={$_.IPv4Address.IPAddress}}
```

优先使用当前联网网卡的地址，例如 WLAN 或以太网对应的 IPv4。

## 云盘账号和密码

云盘使用 SFTPGo 社区版，镜像是固定版本 `drakkan/sftpgo:v2.7.5`。它是免费开源软件，部署在你自己的 WSL/G 盘里，不依赖第三方网盘账号。

普通用户密码文件：

```bash
/home/lxhb/.local/var/brain/secrets/sftpgo-user.txt
```

管理员密码文件：

```bash
/home/lxhb/.local/var/brain/secrets/sftpgo-admin.txt
```

两个文件第一行是用户名，第二行是密码。在 Windows PowerShell 查看普通用户信息：

```powershell
wsl.exe -d Ubuntu-22.04 -- cat /home/lxhb/.local/var/brain/secrets/sftpgo-user.txt
```

查看管理员信息：

```powershell
wsl.exe -d Ubuntu-22.04 -- cat /home/lxhb/.local/var/brain/secrets/sftpgo-admin.txt
```

不要把这两个文件提交到 Git，也不要截图发给别人。

## 云盘自动入库

私有云盘目录已经接入 Brain 的 watcher：

```text
SFTPGo 上传目录： /home/lxhb/.local/var/brain/cloud
Backend 容器路径： /app/data/cloud
```

通过 `http://brain.local:8090/web/client` 上传这些类型时，会自动进入 Brain 笔记库并排队 OCR：

```text
.pdf .png .jpg .jpeg .txt .md .markdown .docx
```

其他类型仍只作为云盘文件保存，不会进入知识库。每日 03:00 还有一次全量兜底扫描；如果云盘上传时 watcher 正好重启，这个扫描会补录新文档。

删除云盘中的受支持文件时，Brain 中对应笔记记录和缩略图也会被 watcher 删除。如果不希望某个文件进入知识库，可以放在非上述扩展名的文件里，或先在 Brain 设置页临时停用 `/app/data/cloud` 监听目录。

## Brain 网页直传私有云

从 Brain 主界面 `8080` 上传的受支持文档，不再先落到 `synced_notes`，而是直接写入私有云盘：

```text
/home/lxhb/.local/var/brain/cloud/from-brain/<device>-<app>/<yyyymmdd>/
```

上传接口会在保存后立即把文件插入 Brain 数据库并加入 OCR 队列；watcher 仍会按路径和哈希去重兜底。因此不需要再手动复制文件到同步目录，也不需要打开 `8090` 云盘页面。

验证方法：

```bash
curl -sS \
  -F 'files=@/tmp/test.md' \
  -F 'device=test' \
  -F 'app=verification' \
  http://127.0.0.1:8080/api/upload
```

返回里应包含 `"storage": "cloud"`、`"enqueue": "queued"`。物理文件应出现在 `/home/lxhb/.local/var/brain/cloud/from-brain/...`。测试后可用笔记删除接口加 `hard=true` 清理测试记录和物理文件。

## 手机连接助手

打开：

```text
http://brain.local:8080/connect
```

这个页面会显示当前浏览器实际使用的访问地址、固定地址 `http://brain.local:8080`、云盘客户端地址、Syncthing 地址、云盘目录规则和磁盘用量。手机端底部导航有“连接”，桌面端侧边栏叫“手机连接”。

如果手机暂时无法解析 `brain.local`，可以在同一局域网的另一台设备打开 `/connect`，确认当前可用入口；仍不支持 mDNS 的设备才需要临时使用物理机 IP。该页面只展示地址和路径信息，不显示账号密码。

## 启动、停止和状态

进入 WSL 运行目录：

```powershell
wsl.exe -d Ubuntu-22.04
cd /home/lxhb/brain
```

启动全部服务，包括 Syncthing 和私有云盘：

```bash
./scripts/deploy.sh --sync
```

如果镜像已经构建过，只是重启或更新配置，用下面命令更快：

```bash
docker compose --profile sync up -d
```

查看状态：

```bash
docker compose ps
docker stats --no-stream
```

查看日志：

```bash
./scripts/deploy.sh --logs
docker compose logs -f cloud
docker compose logs -f backend
```

停止全部服务：

```bash
./scripts/deploy.sh --stop
```

## 备份

### 数据库手动备份

```bash
cd /home/lxhb/brain
./scripts/deploy.sh --backup
```

备份会生成到：

```bash
/home/lxhb/.local/var/brain/backups/
```

### 数据库每日自动备份

```cron
0 2 * * * /home/lxhb/brain/scripts/backup.sh >> /home/lxhb/.local/var/brain/backups/cron.log 2>&1
```

该任务已安装在 WSL 当前用户的 cron 中。脚本保留最近 14 份数据库备份。查看任务：

```bash
crontab -l
```

### 云盘文件备份

云盘原始文件在：

```bash
/home/lxhb/.local/var/brain/cloud
```

可以打包一份到另一个硬盘或网络位置：

```bash
tar -czf /home/lxhb/brain-cloud-files-$(date +%Y%m%d).tar.gz \
  -C /home/lxhb/.local/var/brain cloud
```

如果直接复制整个 `ext4.vhdx`，必须先在 PowerShell 停止 WSL：

```powershell
wsl.exe --shutdown
Copy-Item 'G:\WSL\Ubuntu-22.04\ext4.vhdx' 'G:\WSL\backup\Ubuntu-22.04-ext4.vhdx'
```

运行中复制 VHDX 可能得到不一致的备份。

## 数据库恢复

先确认备份文件名，例如 `brain_20260824_233710.db.gz`：

```bash
cd /home/lxhb/brain
./scripts/deploy.sh --stop
gunzip -k /home/lxhb/.local/var/brain/backups/brain_20260824_233710.db.gz
python3 - <<'PY'
import sqlite3
p = '/home/lxhb/.local/var/brain/backups/brain_20260824_233710.db'
c = sqlite3.connect(p)
print(c.execute('PRAGMA integrity_check').fetchone()[0])
c.close()
PY
cp /home/lxhb/.local/var/brain/brain.db /home/lxhb/.local/var/brain/brain.db.before-recovery
cp /home/lxhb/.local/var/brain/backups/brain_20260824_233710.db /home/lxhb/.local/var/brain/brain.db
./scripts/deploy.sh --sync
```

恢复前务必确认 `integrity_check` 输出 `ok`。

## 物理 IP 或 WSL IP 变化后

项目里有端口转发脚本：

```text
F:\桌面\Brain\scripts\fix-wsl-portproxy.ps1
```

它会刷新这些端口：

```text
8080, 8000, 8384, 8090, 22000, 21027
```

在管理员 PowerShell 执行：

```powershell
powershell.exe -NoProfile -ExecutionPolicy Bypass ^
  -File 'F:\桌面\Brain\scripts\fix-wsl-portproxy.ps1' -RegisterTask
```

`-RegisterTask` 会注册登录任务，开机登录后自动刷新 WSL NAT 地址。执行完成后重新查看物理机局域网 IP，然后用新 IP 访问：

```text
http://<新的局域网IP>:8080
http://<新的局域网IP>:8090/web/client
```

如果只改了 Wi-Fi/以太网 IP，通常 `0.0.0.0` 的 portproxy 规则仍然有效；如果 WSL 重启过，建议重新执行一次脚本。

### 手机固定访问名

项目里的 `scripts/brain-mdns.py` 会把当前局域网地址发布为：

```text
brain.local
```

手机和电脑连同一个 Wi-Fi 时，可以直接使用：

```text
http://brain.local:8080
http://brain.local:8090/web/client
```

不需要每次查物理机 IP。这个服务由计划任务 `Brain mDNS Alias` 在开机/登录后自动启动。如果手机浏览器暂时找不到 `.local` 地址，请确认手机 Wi-Fi 没有开启会阻断 mDNS 的“隐私保护”或访客网络。

重新注册该任务时，在管理员 PowerShell 执行：

```powershell
powershell.exe -NoProfile -ExecutionPolicy Bypass ^
  -File 'F:\桌面\Brain\scripts\register-brain-mdns.ps1'
```

## 内存轻量化配置

当前 Compose 资源限制如下：

| 服务 | 内存限制 | 说明 |
| --- | ---: | --- |
| backend | 512 MiB | 单 Uvicorn worker |
| frontend | 128 MiB | Nginx 静态前端 |
| cloud | 128 MiB | SFTPGo Web 云盘 |
| syncthing | 256 MiB | 笔记同步 |

`.env.example` 中的轻量化参数：

```env
UVICORN_WORKERS=1
OCR_WORKERS=1
OCR_PAGE_PARALLELISM=2
PDF_RENDER_ZOOM=1.25
```

小内存机器不建议调高这些值。OCR 使用外部视觉模型时，主要内存压力来自 PDF 渲染和大文件读取，降低并发比减少 worker 更有效。

## 云盘升级

升级前先备份数据库和账号库：

```bash
cp /home/lxhb/.local/var/brain/sftpgo/config/sftpgo.db \
   /home/lxhb/.local/var/brain/sftpgo/config/sftpgo.db.backup
```

修改 `docker-compose.yml`：

```yaml
image: drakkan/sftpgo:<新版本号>
```

然后执行：

```bash
cd /home/lxhb/brain
docker compose pull cloud
docker compose up -d cloud
```

不要使用 `latest` 作为长期生产版本，避免一次升级引入不兼容变更。

## 本地 LM Studio 模型

Brain 当前使用本机 LM Studio 提供对话模型和向量模型：

| 用途 | API ID | 说明 |
| --- | --- | --- |
| OCR / 结构化 | `qwen3.5-4b` | 用户所说的 Qwen3.5 4B；API ID 使用短横线 |
| RAG 问答 | `qwen3.5-4b` | 与结构化共用同一个本地模型 |
| 向量嵌入 | `text-embedding-nomic-embed-text-v1.5` | 输出 768 维向量 |

WSL 容器不能访问 `127.0.0.1:1234`，所以 Brain 的 `.env` 必须使用：

```env
OPENAI_API_KEY=lm-studio
OPENAI_BASE_URL=http://host.docker.internal:1234/v1
LLM_MODEL=qwen3.5-4b
QA_MODEL=qwen3.5-4b
EMBEDDING_MODEL=text-embedding-nomic-embed-text-v1.5
EMBEDDING_DIM=768
```

Windows 手动启动方式：

```powershell
powershell.exe -NoProfile -ExecutionPolicy Bypass ^
  -File 'F:\桌面\Brain\scripts\start-brain-lmstudio.ps1'
```

当前用户启动文件夹里已放置快捷方式 `Brain LM Studio.lnk`，Windows 登录后会自动执行同一脚本：先确认 `1234` 服务已启动，再按需加载两个模型。两个模型的空闲 TTL 已设置为一年，避免嵌入模型一小时后被自动卸载。

Qwen3.5 有时会先输出 reasoning 内容再输出正式内容。Brain 的文本结构化代码已经兼容 `message.content` 为空时回退读取 `message.reasoning_content`，并对文本/OCR 调用启用 JSON Schema 和 180 秒超时。

更换嵌入模型时要特别小心：不同嵌入模型维度通常不同，例如旧 BGE 是 1024 维，Nomic 是 768 维。余弦检索遇到维度不一致会返回 0，不会报错，但旧笔记会查不到。换嵌入模型前先备份数据库，然后把所有 done 状态笔记重新生成向量和链接。本次切换已完成迁移：3 条旧笔记全部从 1024 维重建为 768 维，并重建了关联边。

本地问答速度取决于显卡/CPU 和上下文长度。实测简单知识库问题约需 1-2 分钟；如果经常用于大文档或高频问答，建议后续换更小/更快的模型，或把问答模型与 OCR 模型分开部署。

## 常见问题

### `8090` 打不开

在 WSL 检查：

```bash
cd /home/lxhb/brain
docker compose ps cloud
curl -i http://127.0.0.1:8090/healthz
```

如果本机正常但局域网打不开，在管理员 PowerShell 刷新 portproxy 和防火墙：

```powershell
powershell.exe -NoProfile -ExecutionPolicy Bypass ^
  -File 'F:\桌面\Brain\scripts\fix-wsl-portproxy.ps1'
```

### 上传的笔记看不到

如果打开 Brain 后笔记像被清空了，先不要重建数据。最常见原因是 Docker Desktop/WSL 重启后绑定挂载偶发脱离：真实文件仍在 WSL 数据目录中，但容器暂时看到了空目录。

Windows 登录启动脚本现在会自动写入探针文件并从 `brain-backend` 容器读取；发现不一致时自动执行修复命令。也可以手动运行：

```powershell
powershell.exe -NoProfile -ExecutionPolicy Bypass ^
  -File 'F:\桌面\Brain\scripts\ensure-brain-mount.ps1'
```

修复逻辑会重建 `backend`、`cloud` 和 `syncthing` 容器，然后等待 `/api/health` 恢复。它不会删除、移动或覆盖 `/home/lxhb/.local/var/brain` 里的数据。

检查 `.env` 是否仍然是：

```env
BRAIN_DATA_DIR=/home/lxhb/.local/var/brain
```

再确认数据库里的历史路径仍然映射为容器内 `/app/data`：

```bash
grep '^BRAIN_DATA_DIR=' .env
docker inspect brain-backend --format '{{json .Mounts}}'
```

不要手工把数据库里的 `/app/data/...` 替换成 Linux 宿主机路径。

### 忘记云盘管理员密码

用密码文件查看：

```bash
cat /home/lxhb/.local/var/brain/secrets/sftpgo-admin.txt
```

如果确实要重置管理员密码，可先停止云盘，再运行：

```bash
cd /home/lxhb/brain
docker compose stop cloud
docker compose run --rm cloud sftpgo resetpwd \
  --admin brain-cloud-admin \
  --config-dir /var/lib/sftpgo
docker compose start cloud
```

按提示输入新密码后，同步更新 `secrets/sftpgo-admin.txt`。

### Docker 拉取镜像返回 403

这是镜像加速器对部分仓库不可用，不代表项目故障。可以稍后重试、临时更换可用加速器，或者使用已经下载好的本地镜像。当前服务使用的镜像已经在本机。

## 安全边界

- 当前云盘适合家庭/个人局域网使用，HTTP 不应直接暴露公网。
- 公网访问请使用 Caddy HTTPS、VPN、Tailscale/WireGuard，或在反向代理层加认证。
- 公网部署 Brain 时设置强随机 `BRAIN_API_KEY`。
- `secrets/` 目录不要放进 Git；`.gitignore` 应继续排除真实 `.env` 和敏感凭据。

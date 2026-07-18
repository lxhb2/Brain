# Brain · 个人手写笔记知识图谱

把多设备的手写笔记（GoodNotes / Notability / OneNote / 手拍白板…）自动变成一个可检索、可关联、可问答的「知识星座」。

- **自动入库**：watchdog 实时监听同步文件夹 + 每日凌晨全量兜底扫描
- **OCR + 结构化**：GPT-4o 视觉模型抽取标题 / 摘要 / 关键词 / OCR 文本 + embedding
- **知识图谱**：候选链接 = α·语义相似 + β·关键词重合 + γ·时间衰减，React Flow 可视化
- **RAG 问答**：向量检索 Top-K → LLM 生成 → 附引用笔记，支持 👍/👎 反馈自学习
- **极轻量**：后台常驻 ~100MB；原始文件不进库，SQLite 单文件 ~60MB / 千张
- **Demo 模式**：不配 OpenAI Key 也能端到端跑通（模拟 OCR / 问答 / 图谱）

---

## 架构

```
各设备笔记 App ──自动导出──▶ Syncthing ──▶ 中转机 synced_notes/
                                                │
                                ┌───────────────┴───────────────┐
                                ▼                               ▼
                          watchdog 实时监听            每日 03:00 全量扫描
                                │                               │
                                └──────────┬────────────────────┘
                                           ▼
                              OCR Pipeline (GPT-4o) + Embedding
                                           │
                            ┌──────────────┼──────────────┐
                            ▼              ▼              ▼
                         SQLite        缩略图         候选链接
                            │
                      FastAPI (端口 8000) ─── 任意设备浏览器访问
                      ├ /graph   知识图谱 (React Flow)
                      ├ /qa      RAG 智能问答
                      └ /notes   笔记浏览 (原图 + OCR 对照)
```

## 项目结构

```
.
├── backend/                # Python FastAPI 后端
│   ├── main.py             # 入口 + 静态托管 + lifespan 启动后台服务
│   ├── config.py           # pydantic-settings 配置
│   ├── database.py         # SQLite + 内存向量检索
│   ├── watcher.py          # watchdog 文件监听
│   ├── ocr_processor.py    # OCR + 结构化 + embedding
│   ├── qa_engine.py        # RAG 问答
│   ├── graph_api.py        # 图谱构建与查询
│   ├── feedback.py         # 👍/👎 反馈
│   ├── scheduler.py        # APScheduler 定时扫描 + 处理队列
│   ├── routes/             # API 路由分组
│   └── requirements.txt
├── frontend/               # React + Vite + React Flow
│   ├── src/
│   │   ├── pages/          # Graph / QA / Notes / NoteDetail
│   │   ├── components/     # Layout / NoteNode / GraphFilters / ...
│   │   ├── api/            # 后端 API 封装
│   │   └── lib/            # 力导向布局等工具
│   └── nginx.conf
├── Dockerfile.backend
├── Dockerfile.frontend
├── docker-compose.yml
└── .env.example
```

---

## 快速开始

### 方式一：Docker Compose（推荐）

```bash
# 1. 复制环境配置（可选：填入 OPENAI_API_KEY 启用真实 OCR）
cp .env.example .env

# 2. 一键启动
docker compose up -d --build

# 3. 浏览器访问
open http://localhost:8080
```

后端 API 在 `http://localhost:8000`，前端在 `http://localhost:8080`。

### 方式二：本地开发（前后端分离热更新）

```bash
# 后端
cd backend
pip install -r requirements.txt
python main.py            # 监听 0.0.0.0:8000

# 前端（另开终端）
cd frontend
npm install
npm run dev               # 监听 5173，自动代理 /api → :8000
```

浏览器访问 `http://localhost:5173`。

---

## 服务器部署

Brain 支持三种部署场景，按你的需求选一种即可。

### 场景一：本地 PC / WSL（局域网访问）

适合：只想在家里用，手机和 PC 在同一 WiFi。

```bash
# WSL 或 Linux PC 上一键启动
./scripts/deploy.sh
```

脚本会自动：
- 检查并提示安装 Docker
- 创建 `.env` 配置文件
- 初始化数据目录
- 启动前后端容器

启动后用 `http://你PC的局域网IP:8080` 访问。

**WSL 用户额外步骤**（让局域网设备能访问 WSL 内的服务）：

```powershell
# 在 Windows PowerShell（管理员）里执行
# 获取 WSL 的 IP
$wslIP = wsl hostname -I
# 把 Windows 的 8080 端口转发到 WSL
netsh interface portproxy add v4tov4 listenport=8080 listenaddress=0.0.0.0 connectport=8080 connectaddress=$wslIP
# 开放防火墙
New-NetFirewallRule -DisplayName "Brain" -Direction Inbound -LocalPort 8080 -Protocol TCP -Action Allow
```

**WSL 开机自启**（systemd 方式）：

```bash
# 在 WSL 里启用 systemd
sudo tee -a /etc/wsl.conf <<EOF
[boot]
systemd=true
EOF
# 然后在 PowerShell 执行 wsl --shutdown 重启 WSL

# 安装 brain 服务
sudo cp scripts/brain.service /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable --now brain
```

### 场景二：云服务器 + HTTPS（生产部署）

适合：要在外网访问、用域名、有 HTTPS（手机 PWA 必需）。

**前提**：已有一台云服务器（推荐 Oracle Cloud Always Free 2C12G 或阿里云 99 元/年）+ 一个域名。

```bash
# 1. SSH 登录服务器，拉取代码
git clone <你的仓库地址> /opt/brain
cd /opt/brain

# 2. 编辑 Caddyfile，把 brain.example.com 改成你的域名
nano Caddyfile

# 3. 编辑 .env，填入 OpenAI API Key
cp .env.example .env
nano .env

# 4. 生产模式启动（自动 HTTPS）
./scripts/deploy.sh --prod
```

脚本会用 `docker-compose.yml` + `docker-compose.prod.yml` 启动：
- Caddy 自动申请 Let's Encrypt 证书并续期
- 前端走 Caddy 443 端口
- 后端仅在容器内网，不对外暴露

**域名解析**：在域名服务商把 A 记录指向服务器公网 IP，等几分钟生效即可访问 `https://你的域名`。

**服务器端口开放**：
- 阿里云/腾讯云：控制台 → 安全组 → 开放 80 + 443
- Oracle Cloud：Networking → Security Lists → 添加 80 + 443
- 服务器防火墙：`sudo ufw allow 80,443/tcp`

### 场景三：裸金属部署（不用 Docker）

适合：服务器配置很低（1C1G），Docker 占资源太多。

```bash
# 1. 装依赖
cd backend
python3.12 -m venv .venv
.venv/bin/pip install -r requirements.txt

# 2. 构建前端
cd ../frontend
pnpm install && pnpm run build

# 3. 把前端构建产物软链到 backend 能找到的位置
ln -s ../frontend/dist ../backend/../frontend/dist

# 4. 配 .env
cd ..
cp .env.example .env
nano .env

# 5. 安装 systemd 服务
sudo cp scripts/brain.service /etc/systemd/system/
sudo nano /etc/systemd/system/brain.service  # 修改路径
sudo systemctl daemon-reload
sudo systemctl enable --now brain

# 6. 验证
curl http://localhost:8000/api/health
```

### 配置 Syncthing 笔记同步

启动 Brain 时加 `--sync` 参数，会同时启动 Syncthing 容器：

```bash
./scripts/deploy.sh --sync
```

然后访问 `http://服务器IP:8384` 配置 Syncthing：
1. 设置管理密码
2. 添加设备（手机/平板上的 Syncthing）
3. 共享 `synced_notes` 文件夹

手机端装 Syncthing（Android）/ Möbius Sync（iOS），扫码连接即可。

### 数据备份

**手动备份**：

```bash
./scripts/backup.sh
```

**定时备份**（推荐）：

```bash
crontab -e
# 每天凌晨 2 点备份，保留 14 天
0 2 * * * /opt/brain/scripts/backup.sh >> /opt/brain/data/backups/cron.log 2>&1
```

备份文件位于 `data/backups/brain_YYYYMMDD_HHMMSS.db.gz`。

### 运维命令速查

| 操作 | 命令 |
|------|------|
| 启动（开发） | `./scripts/deploy.sh` |
| 启动（生产 HTTPS） | `./scripts/deploy.sh --prod` |
| 启动 + Syncthing | `./scripts/deploy.sh --sync` |
| 查看日志 | `./scripts/deploy.sh --logs` |
| 停止 | `./scripts/deploy.sh --stop` |
| 更新代码并重启 | `./scripts/deploy.sh --update` |
| 备份数据库 | `./scripts/deploy.sh --backup` |
| 容器状态 | `docker compose ps` |
| 进入后端容器 | `docker compose exec backend bash` |
| 查看 systemd 服务 | `systemctl status brain` |
| systemd 日志 | `journalctl -u brain -f` |

---

## 配置说明

复制 `.env.example` 为 `.env`，按需修改：

| 变量 | 默认 | 说明 |
|------|------|------|
| `OPENAI_API_KEY` | （空） | 不填则进入 Demo 模式 |
| `OPENAI_BASE_URL` | （空） | 兼容第三方 OpenAI 端点 |
| `LLM_MODEL` | `gpt-4o` | 视觉 OCR / 对话模型 |
| `EMBEDDING_MODEL` | `text-embedding-3-small` | 向量模型 |
| `SYNCED_NOTES_ROOT` | `data/synced_notes` | 笔记同步根目录 |
| `DB_PATH` | `data/brain.db` | SQLite 路径 |
| `LINK_ALPHA` / `LINK_BETA` / `LINK_GAMMA` | 0.6 / 0.3 / 0.1 | 链接权重三分量 |
| `LINK_WEIGHT_THRESHOLD` | 0.35 | 候选链接入图阈值 |

### 监听目录（多设备）

默认监听 `synced_notes/` 下的四个子目录，每个对应一种设备来源：

```
data/synced_notes/
├── ipad-goodnotes/      # iPad GoodNotes 导出
├── android-notes/       # 安卓笔记
├── pc-onenote/          # 电脑 OneNote
└── camera-shots/        # 手拍白板 / 照片
```

在 `backend/config.py` 的 `WATCH_DIRS` 中可增删目录与设备标签。

---

## 多设备同步方案

每台设备的笔记 App 设置「自动导出到同步文件夹」，再用 Syncthing 把这些文件夹同步到中转机的 `data/synced_notes/<对应子目录>`：

```
iPad (GoodNotes)  ──自动备份──▶ Syncthing ──┐
Android (笔记)    ──自动同步──▶ Syncthing ──┤──▶ 中转机 synced_notes/
PC (OneNote)      ──导出 PDF──▶ Syncthing ──┤
手拍照片          ──自动下载──▶ Syncthing ──┘
```

文件一旦出现在监听目录，watchdog 立即触发处理：OCR → 入库 → 生成缩略图 → 计算候选链接 → 图谱更新。

---

## API 速览

| 方法 | 路径 | 说明 |
|------|------|------|
| GET | `/api/notes` | 笔记列表（device/app/q/status/limit/offset） |
| GET | `/api/notes/{id}` | 笔记详情 |
| GET | `/api/notes/{id}/file` | 原始文件 |
| GET | `/api/notes/{id}/thumbnail` | 缩略图 |
| POST | `/api/notes/reprocess/{id}` | 重新 OCR |
| GET | `/api/graph` | 图谱节点与边 |
| GET | `/api/graph/neighbors/{id}` | 邻居节点 |
| POST | `/api/qa/ask` | RAG 问答 |
| GET | `/api/qa/history` | 问答历史 |
| POST | `/api/feedback` | 👍/👎 反馈 |
| GET | `/api/stats` | 统计 |
| GET | `/api/health` | 健康检查 |

---

## 候选链接权重

```
weight = 0.6·cosine_sim(emb_a, emb_b)
       + 0.3·jaccard(keywords_a, keywords_b)
       + 0.1·exp(-|Δt_天| / 30)
```

仅保留 `weight > 0.35` 的链接。反馈 👍 提升引用笔记间权重 +0.05，👎 降低 -0.10（clamp 到 [0,1]）。

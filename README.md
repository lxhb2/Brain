# Brain - 个人知识库与成长系统

> 本项目由 AI 编程实现。

Brain 不只是一个笔记存储工具，而是一个帮助你把信息转化为实操经验、持续进化的「第二大脑」。

核心理念：**知识库的价值 = 知识密度 x 调用频次 x 验证深度**。只存真正做过、验证过的活知识，外部资料放仓库区，噪音自动过滤。

---

## 核心功能

### 自动入库与 OCR

- watchdog 实时监听多设备同步文件夹，每日凌晨全量兜底扫描
- 支持 PDF / 图片 / TXT / Markdown / DOCX
- 本地或云端 OCR 抽取文本，LLM 结构化生成标题、摘要、关键词和向量
- Markdown 中本地引用的图片也会被 OCR，并合并到同一条笔记里
- Markdown 处理完成后会自动生成持久化整合包：`document.md`、`assets/` 图片和单文件 ZIP 同时保存在 `/app/data/markdown_bundles/`
- 生成缩略图，原图保留在数据目录

### Markdown 与 Mermaid 图

笔记详情页使用 Markdown 渲染，支持 GFM 表格、代码块和内嵌图片。Markdown 引用的本地图片会通过受限预览接口读取，仅允许监听目录中的图片。OCR 识别到流程、箭头或分支关系时，会额外生成 `mermaid` 字段并渲染为关系图。你可以在详情页手动修正 OCR 文本和 Mermaid 代码，也能在保存前切换“编辑 / 预览”查看最终效果。

Markdown 整合包会持久化到 `/app/data/markdown_bundles/<note_id>/`。这里同时保留 `document.md + assets/` 的可读目录和 `*-markdown-bundle.zip` 单文件；ZIP 内的 `document.md` 已把引用改成本地 `assets/` 路径，`manifest.json` 记录原文件对应关系。Mermaid 代码会追加到文档末尾，解压后可整体移动到 Obsidian 或其他 Markdown 工具中。旧笔记可用 `/api/system/backfill-markdown-bundles?limit=100` 补跑。

### 成长闭环（Growth）

访问 `http://127.0.0.1:8080/growth`

| 环节 | 说明 |
|------|------|
| 入库分诊 | LLM 自动判断每条笔记是 `practice`（实操经验）/ `reference`（外部资料）/ `noise`（噪音），并提取条件、动作、结果、证据、下一步 |
| 调用统计 | 问答答案中真实引用的笔记才累计使用次数 |
| 知识卡片 | 每次问答可沉淀为结构化卡片，含核心结论、落地场景和检验问题 |
| 间隔复验 | 卡片根据回答质量进入复验队列，答对延长间隔，答错缩短间隔并进入错题本 |
| 卡片复用 | 后续问答真实引用卡片（`[卡片id]`）时自动累计复用次数，卡片列表与成长页可查 |
| 每日审核 | 每天 23:05 AI 审计当日记录：哪些值得保留、哪些理解有偏差、明天做什么调整 |

### 成长感知混合检索

问答检索不是单纯的向量相似度，排序公式：

```
score = 0.70 * cosine_similarity(query, note)
      + 0.25 * keyword_overlap(query, note_all_fields)
      + growth_boost
```

其中 `growth_boost` 包括：

- `practice` 笔记 +0.05
- 已被正确复验卡片引用的笔记 +0.08
- 高频使用笔记最高 +0.032（use_count 封顶 8 次）
- `reference` 笔记 -0.03（避免收藏型资料淹没活知识）

已沉淀的知识卡片也会回流到 Agent 上下文，让结论可以被复用。

### RAG 问答 + Agent 工具

访问 `http://127.0.0.1:8080/qa`

- 初始检索：成长感知混合排序 Top-5 笔记 + 相关知识卡片 + 用户长期记忆
- Agent 可主动调用工具补检：`search_notes` / `search_memory` / `add_memory`
- 单轮最多 3 次工具调用，防止死循环
- 答案强制附带 `[note_id]` 引用，只有真实出现的引用才计入调用频次
- 复用知识卡片时用 `[卡片id]` 引用，例如 `[卡片5]`，卡片复用次数和上次复用时间会自动更新
- 多轮对话支持最近 5 轮历史上下文

### 知识图谱

访问 `http://127.0.0.1:8080/graph`

候选链接权重 = `0.6*语义相似 + 0.3*关键词重合 + 0.1*时间衰减`，React Flow 可视化展示。

### 私有云盘（SFTPGo）

访问 `http://brain.local:8090/web/client`

- 从 Brain 主界面（8080 端口）上传的文档会自动落入 `/app/data/cloud/` 并被 watcher 扫描入库
- 云盘文件同时保存在本地磁盘上，不会因物理机 IP 变化而消失
- 支持手机端直接上传到云盘目录，后端自动识别来源为 `cloud-sftpgo`

### 活动日志

访问 `http://127.0.0.1:8080/logs`

自动记录什么模型在什么时候完成了什么任务、哪个设备上传了哪个文件、何时执行了备份。

### 扫描忽略名单

如果某个源文件只是历史草稿、重复截图或不需要入库的附件，可以加入忽略名单。扫描器和 watcher 会按完整路径及文件哈希跳过它，避免手动删除记录后又被每日全量扫描“复活”：

```http
POST /api/system/ignored-files
Content-Type: application/json

{
  "file_path": "/mnt/d/path/to/file.jpg",
  "file_hash": "optional-sha256",
  "reason": "historical duplicate"
}
```

### 固定访问地址

通过 mDNS 注册 `brain.local`，局域网内手机和电脑无需查询 IP：

```
http://brain.local:8080    # Brain 主界面
http://brain.local:8000    # 后端 API
http://brain.local:8090    # SFTPGo 云盘
http://brain.local:8384    # Syncthing
```

如果 `brain.local` 无法解析（部分 Android 设备不支持 mDNS），仍可通过 Windows 物理机 IP + 8080 访问。脚本 `scripts/register-brain-mdns.ps1` 可注册开机自启动的 mDNS 广播。

---

## 本地模型（LM Studio）

Brain 默认连接本机 LM Studio 提供的 OpenAI 兼容 API：

| 用途 | 模型 | 说明 |
|------|------|------|
| OCR 结构化 / RAG 问答 / 分诊 / 审核 | `qwen3.5-4b` | Qwen3.5 4B，API ID 使用短横线 |
| 向量嵌入 | `text-embedding-nomic-embed-text-v1.5` | 输出 768 维向量 |

`.env` 关键配置：

```env
OPENAI_API_KEY=lm-studio
OPENAI_BASE_URL=http://host.docker.internal:1234/v1
LLM_MODEL=qwen3.5-4b
QA_MODEL=qwen3.5-4b
EMBEDDING_MODEL=text-embedding-nomic-embed-text-v1.5
EMBEDDING_DIM=768
BRAIN_DATA_DIR=/home/lxhb/.local/var/brain
```

WSL 容器无法访问 `127.0.0.1:1234`，必须用 `host.docker.internal`。

Windows 启动脚本 `scripts/start-brain-lmstudio.ps1` 会确认 LM Studio 服务已启动并按需加载两个模型，已注册到用户登录自启动。

---

## 架构

```
iPad (GoodNotes) --Syncthing--> \
Android (笔记)   --Syncthing-->  \
PC (OneNote)     --Syncthing-->   >--> data/synced_notes/<device-app>/
手拍照片          --Syncthing--> /
SFTPGo 云盘上传   -------------> data/cloud/
                                        |
                        watchdog 实时监听 + 每日 03:00 全量扫描
                                        |
                              OCR Pipeline + Embedding
                                        |
                    SQLite + 缩略图 + 候选链接 + 入库分诊
                                        |
                    FastAPI (8000) <-- nginx (8080) <-- 浏览器/PWA
                    |       |       |       |
                 /graph   /qa   /notes   /growth
                知识图谱  问答   笔记浏览  成长面板
```

## 项目结构

```
.
├── backend/
│   ├── main.py             # FastAPI 入口 + lifespan 启动后台服务
│   ├── config.py           # pydantic-settings 配置
│   ├── database.py         # SQLite + 混合检索 + 向量相似度
│   ├── watcher.py          # watchdog 文件监听
│   ├── ocr_processor.py    # OCR + 结构化 + embedding
│   ├── bundle_builder.py   # Markdown 文字 + 图片整合包
│   ├── qa_engine.py        # RAG 问答 + Agent 工具调用
│   ├── graph_api.py        # 图谱构建与查询
│   ├── feedback.py         # 反馈处理
│   ├── growth.py           # 入库分诊 + 每日成长审核
│   ├── scheduler.py        # APScheduler 定时任务
│   ├── settings_store.py   # 运行时监听目录持久化
│   └── routes/             # API 路由分组
├── frontend/src/
│   ├── pages/              # Graph / QA / Notes / Growth / Logs / Settings ...
│   ├── components/         # Layout / NoteNode / GraphFilters ...
│   └── api/client.ts       # 后端 API 封装
├── scripts/                # 部署、备份、mDNS、端口转发等脚本
├── docs/BUILD_YOUR_OWN_KNOWLEDGE_BASE.md  # 从零搭建个人知识库实操手册
├── docs/OPERATIONS.md      # 详细运维手册
├── Dockerfile.backend
├── Dockerfile.frontend
└── docker-compose.yml
```

---

## 快速开始

### Docker Compose（推荐）

```bash
cp .env.example .env
# 编辑 .env 填入模型配置
docker compose up -d --build
```

前端 `http://localhost:8080`，后端 `http://localhost:8000`。

### 本地开发

```bash
# 后端
cd backend
pip install -r requirements.txt
python main.py

# 前端（另开终端）
cd frontend
npm install && npm run dev
```

浏览器访问 `http://localhost:5173`。

---

## 定时任务

所有任务使用 Asia/Shanghai 时区：

| 时间 | 任务 |
|------|------|
| 02:30 | 自动备份数据库（保留 14 天） |
| 03:00 | 全量扫描监听目录 |
| 03:30 | 记忆权重衰减 + 链接权重衰减 |
| 23:00 | 每日笔记归纳 |
| 23:05 | 成长维护：分诊积压笔记 + AI 每日审核 |
| 每小时 :15 | 自动重试失败的 OCR（最多 3 次） |

分诊每次最多处理 3 条，避免占满本地 Qwen 模型。

---

## 数据安全

当前数据目录 `/home/lxhb/.local/var/brain` 位于 WSL 的 ext4 虚拟磁盘内，实际占用 `G:\WSL\Ubuntu-22.04\ext4.vhdx`。物理机 IP 变化不影响文件和数据。

- 数据库每日 02:30 自动备份到 `data/backups/`
- 手动备份：`./scripts/backup.sh`
- 不要把数据放在 `/mnt/c` 或 `/mnt/f` 等 Windows 挂载路径上（性能差且权限不稳定）
- Windows 登录时会自动执行 `scripts/ensure-brain-mount.ps1` 检查 Docker 挂载是否脱离真实数据目录；发现异常会自动重建容器并等待健康检查，避免笔记“刷新后消失”

完整运维说明见 [docs/OPERATIONS.md](docs/OPERATIONS.md)，从零搭建教程见
[docs/BUILD_YOUR_OWN_KNOWLEDGE_BASE.md](docs/BUILD_YOUR_OWN_KNOWLEDGE_BASE.md)。

---

## API 速览

| 方法 | 路径 | 说明 |
|------|------|------|
| GET | `/api/health` | 健康检查 + 当前模型配置 |
| GET | `/api/stats` | 统计（含成长指标） |
| GET | `/api/notes` | 笔记列表 |
| GET | `/api/notes/{id}` | 笔记详情 |
| POST | `/api/qa/ask` | RAG 问答 |
| GET | `/api/cards` | 知识卡片列表 |
| GET | `/api/cards/{id}` | 卡片详情（含复用次数） |
| GET | `/api/cards/due/review` | 到期复验卡片 |
| POST | `/api/system/growth-triage?limit=3` | 手动触发入库分诊 |
| POST | `/api/system/growth-review` | 手动触发每日审核 |
| GET | `/api/system/growth-reviews` | 最近审核列表 |
| GET | `/api/notes/{id}/bundle` | 下载 Markdown 整合包 |
| GET | `/api/system/ignored-files` | 查看扫描忽略名单 |
| POST | `/api/system/ignored-files` | 增加扫描忽略规则 |
| POST | `/api/system/backfill-markdown-bundles?limit=100` | 补跑已有 Markdown 整合包 |
| GET | `/api/activity-logs` | 活动日志 |
| GET | `/api/graph` | 图谱节点与边 |

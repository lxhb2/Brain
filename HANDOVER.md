# Brain 项目交接文档

> 项目名：Brain · 个人手写笔记知识图谱与 RAG 问答系统
> 文档版本：1.0
> 编写日期：2026-07-22
> 交接人：Brain Dev

---

## 1. 项目概述

Brain 是一个**个人手写笔记知识图谱 + RAG 问答系统**。它把多设备（iPad / Android / PC / 手拍照片）的手写笔记通过 OCR 转成结构化文本，自动构建知识图谱，支持向量检索的 RAG 问答，并在每次问答后将知识沉淀为「知识卡片」，形成「星云图谱」可视化。

核心价值：
- **自动入库**：watchdog 实时监听同步文件夹 + 每日凌晨全量兜底扫描
- **OCR 结构化**：视觉大模型抽取标题 / 摘要 / 关键词 / 正文 + embedding
- **知识图谱**：候选链接 = α·语义相似 + β·关键词重合 + γ·时间衰减，双视图可视化（笔记图谱 + 星云图谱）
- **RAG 问答**：向量检索 Top-K → LLM 生成 → 附引用笔记，👍/👎 反馈自学习
- **知识卡片闭环**：问答后自动生成卡片草稿 → Socratic 提问 → 用户回答 → LLM 评估补充 → 落库建链
- **极轻量**：后台常驻 ~100MB；SQLite 单文件；原始文件不进库
- **Demo 模式**：不配 LLM Key 也能端到端跑通（模拟数据）

---

## 2. 技术栈

| 层 | 技术 | 说明 |
|----|------|------|
| 前端 | React 18 + Vite 6 + TypeScript | SPA，react-router v7 多页路由 |
| 图谱 | React Flow（笔记图谱）+ d3-force（星云图谱） | 双引擎 |
| 样式 | Tailwind CSS 3 | 深色「星空」主题 |
| 状态 | Zustand | 轻量全局状态 |
| 后端 | Python 3.12 + FastAPI + Uvicorn | REST API |
| 文件监听 | watchdog | 实时监听笔记目录 |
| 定时任务 | APScheduler | 全量扫描 / 每日归纳 / 记忆衰减 |
| 数据库 | SQLite（标准库 sqlite3 + 内存向量检索） | MVP 不引入向量数据库 |
| OCR | OpenAI 兼容视觉模型（默认 SiliconFlow）+ 百度 OCR（可选） | 多模态 |
| PDF | PyMuPDF | PDF 转图像喂视觉模型 |
| 文档解析 | python-docx | Word(.docx) 文本抽取 |
| 部署 | Docker Compose + Caddy | 前后端容器化，可选 HTTPS |

---

## 3. 系统架构

```
各设备笔记 App ──自动导出──▶ Syncthing ──▶ 中转机 synced_notes/
                                                │
                                ┌───────────────┴───────────────┐
                                ▼                               ▼
                          watchdog 实时监听            每日 03:00 全量扫描
                                │                               │
                                └──────────┬────────────────────┘
                                           ▼
                              OCR Pipeline（并发 worker 池）
                              │  ├─ 视觉 OCR / 文本抽取
                              │  ├─ LLM 结构化（标题/摘要/关键词）
                              │  └─ Embedding
                              │
                            ┌─┴─────────────┐
                            ▼               ▼
                         SQLite          缩略图        候选链接（异步重算）
                            │
                      FastAPI (端口 8000) ─── 浏览器 / PWA
                      ├ /api/notes   笔记管理
                      ├ /api/graph   知识图谱（笔记 + 卡片）
                      ├ /api/qa      RAG 问答
                      ├ /api/cards   知识卡片
                      └ /api/settings 运行配置
```

### 后端启动流程（main.py lifespan）

1. `init_db()` — 建表 / 兼容性迁移
2. `reset_stale_processing_notes()` — 崩溃恢复（processing → pending）
3. `start_worker()` — 启动 OCR 并发 worker 线程池
4. `start_watcher()` — watchdog 文件监听
5. `start_scheduler()` — 定时任务（全量扫描 / 每日归纳 / 记忆衰减）

---

## 4. 目录结构

```
brain/
├── backend/                    # Python FastAPI 后端
│   ├── main.py                 # 入口 + 静态托管 + lifespan（启动后台服务）
│   ├── config.py               # pydantic-settings 配置 + OCR 并发参数
│   ├── database.py             # SQLite CRUD + 内存向量检索 + 建表迁移
│   ├── watcher.py              # watchdog 文件监听
│   ├── ocr_processor.py        # OCR / 文本抽取 / 结构化 / embedding
│   ├── qa_engine.py            # RAG 问答 + 卡片草稿生成（Agent）
│   ├── graph_api.py            # 图谱构建与查询（笔记 + 卡片）
│   ├── feedback.py             # 👍/👎 反馈 + 链接权重调整
│   ├── scheduler.py            # 并发 worker 线程池 + APScheduler 定时任务
│   ├── baidu_ocr.py            # 百度 OCR 适配
│   ├── settings_store.py       # 运行时设置持久化（文件夹/模型/链接参数）
│   ├── seed_demo.py            # Demo 种子数据
│   ├── routes/
│   │   ├── notes.py            # 笔记 CRUD / 重 OCR / 删除
│   │   ├── graph.py            # 图谱（含 /cards 混合图谱）
│   │   ├── qa.py               # 问答 / 会话 / 长期记忆
│   │   ├── cards.py            # 知识卡片 CRUD / finalize
│   │   ├── feedback.py         # 反馈
│   │   ├── settings.py         # 运行配置
│   │   ├── stats.py            # 统计
│   │   ├── system.py           # 系统运维（扫描/重建链接/清理/归纳）
│   │   └── upload.py           # 多格式文档上传
│   └── requirements.txt
├── frontend/                   # React + Vite 前端
│   ├── src/
│   │   ├── pages/              # Graph / QA / Notes / NoteDetail / Cards / CardDetail / Settings
│   │   ├── components/         # Layout / NebulaGraph / GraphFilters / NodeDetailDrawer / ...
│   │   ├── api/client.ts       # 后端 API 封装 + 类型定义
│   │   ├── lib/                # 力导向布局 / 工具函数
│   │   ├── hooks/              # 自定义 hooks
│   │   └── store.ts            # Zustand 状态
│   └── nginx.conf              # SPA 路由回退 + API 反代
├── scripts/                    # 运维脚本
│   ├── deploy.sh               # 一键部署（dev/prod/sync/update/logs 等）
│   ├── backup.sh               # SQLite 增量备份
│   ├── brain.service           # systemd 服务单元
│   └── cleanup-wsl-docker.ps1  # WSL Docker 磁盘清理（Windows 侧）
├── Dockerfile.backend
├── Dockerfile.frontend
├── docker-compose.yml          # backend + frontend + (可选 syncthing)
├── docker-compose.prod.yml     # 生产 HTTPS（Caddy）
├── Caddyfile                   # Caddy 反代配置
├── .env.example                # 环境变量模板
└── README.md                   # 使用文档
```

---

## 5. 核心功能模块

### 5.1 笔记自动入库

- **监听**：`watcher.py` 用 watchdog 监听 `WATCH_DIRS` 下的目录（默认 4 个设备子目录）
- **兜底**：`scheduler.py` 每日 03:00 全量扫描，防止监听遗漏
- **支持格式**：PDF / PNG / JPG / JPEG / TXT / Markdown / Word(.docx)
- **OCR**：视觉大模型（多模态）抽取标题、摘要、关键词、OCR 原文
- **去重**：按 `file_path` 和 `file_hash` 双重去重
- **重试**：失败自动重试（`retry_count` / `last_error` 字段）

### 5.2 知识图谱（双视图）

- **笔记图谱**（React Flow）：仅笔记节点 + 笔记间链接，语义/关键词/时间三类边
- **星云图谱**（d3-force，`NebulaGraph.tsx`）：笔记（圆形）+ 知识卡片（六边形）混合，Obsidian 风格力导向布局，支持中心节点聚焦（`?center=card:ID`）

### 5.3 RAG 问答（轻量 Agent）

`qa_engine.py` 的 `ask()` 流程：
1. 问题向量化 → 预检索（笔记 + 长期记忆）
2. LLM 带 3 个 tool（search_notes / search_memory / add_memory）补充检索、自我学习
3. 生成答案，用 `[note_id]` 引用来源
4. 写入 `qa_history`（带 session_id），同步 upsert 会话
5. **自动生成知识卡片草稿**（仅当有引用时）

### 5.4 知识卡片闭环（核心新增功能）

完整链路：
```
问答结束 → _generate_card_draft() 生成草稿（title/core_summary/key_conclusion/application_scenario/agent_question）
  → 前端 QA 页弹窗「存为知识卡片」
  → 用户回答 Agent 检验性问题（或跳过）
  → POST /api/cards/finalize
  → LLM 评估 verdict（correct / needs_supplement / skipped）→ 不足时补充
  → 落库 knowledge_cards + 自动建 card→note 链接
  → 星云图谱展示「卡片—笔记」紫色虚线链接
```

### 5.5 长期记忆与反馈自学习

- 反馈 down + correction → 存为 correction 记忆（weight=0.8）
- 反馈 up → 提升相关记忆权重
- LLM 主动 add_memory → 学习用户偏好

### 5.6 OCR 并发优化（最近变更）

- 多 worker 线程池并发消费队列（默认 3，`OCR_WORKERS`）
- 多页 PDF 并发 OCR（默认 4 路，`OCR_PAGE_PARALLELISM`）
- 链接重算异步化（独立线程池，不阻塞 worker）
- OpenAI client `lru_cache` 复用
- PDF 渲染 DPI 降低（zoom 2.0 → 1.5）

---

## 6. 数据库设计

SQLite 单文件，位置由 `DB_PATH` 决定（默认 `data/brain.db`）。共 10 张表：

| 表名 | 用途 | 关键字段 |
|------|------|---------|
| `notes` | 笔记 | file_path, title, ocr_text, summary, keywords(JSON), embedding(JSON), source_device, source_app, status, thumbnail_path, file_hash, manually_edited, retry_count, last_error |
| `links` | 笔记-笔记链接 | source_note_id, target_note_id, weight, reason, link_type |
| `qa_history` | 问答历史 | question, answer, citations(JSON), session_id |
| `qa_sessions` | 会话元信息 | session_id, title, msg_count |
| `feedback` | 反馈 | qa_id, rating, correction |
| `user_memory` | 长期记忆 | type, content, source, weight, embedding(JSON), use_count |
| `knowledge_cards` | 知识卡片 | qa_id, session_id, title, core_summary, key_conclusion, application_scenario, agent_question, user_answer, ai_supplement, source_note_ids(JSON), status |
| `card_links` | 卡片↔笔记/卡片链接 | source_type, source_id, target_type, target_id, weight, reason |
| `daily_summaries` | 每日归纳 | date, content, note_ids |
| `settings` | 运行设置 | key, value(JSON) |

**嵌入向量**以 JSON 字符串存 TEXT 列，检索用内存态余弦相似度（MVP 方案，未引入向量数据库）。

**建表采用「幂等 CREATE + 兼容性迁移」模式**：新增列通过 `ALTER TABLE`（如 `ocr_model`、`manually_edited`、`session_id`），旧库可平滑升级。

---

## 7. API 接口清单

### 笔记 `/api/notes`
| 方法 | 路径 | 说明 |
|------|------|------|
| GET | `/api/notes` | 列表（device/app/q/status/limit/offset） |
| GET | `/api/notes/{id}` | 详情 |
| GET | `/api/notes/{id}/file` | 原始文件 |
| GET | `/api/notes/{id}/thumbnail` | 缩略图 |
| POST | `/api/notes/reprocess/{id}` | 重新 OCR |
| PATCH | `/api/notes/{id}` | 人工编辑 |
| DELETE | `/api/notes/{id}` | 删除（软删除） |
| POST | `/api/notes/{id}/reocr` | 重新 OCR（保留人工编辑） |

### 图谱 `/api/graph`
| 方法 | 路径 | 说明 |
|------|------|------|
| GET | `/api/graph` | 笔记图谱节点与边 |
| GET | `/api/graph/neighbors/{note_id}` | 邻居节点 |
| GET | `/api/graph/cards` | 笔记+卡片混合图谱（支持 center_card_id） |

### 问答 `/api/qa`
| 方法 | 路径 | 说明 |
|------|------|------|
| POST | `/api/qa/ask` | 问答（返回 answer/citations/card_draft 等） |
| GET | `/api/qa/history` | 问答历史 |
| GET/PATCH/DELETE | `/api/qa/sessions...` | 会话管理 |
| GET/POST/PATCH/DELETE | `/api/qa/memories...` | 长期记忆管理 |

### 知识卡片 `/api/cards`
| 方法 | 路径 | 说明 |
|------|------|------|
| GET | `/api/cards` | 卡片列表 |
| GET | `/api/cards/{id}` | 卡片详情（含 links） |
| POST | `/api/cards/finalize` | 提交答案 + LLM 评估 + 落库建链 |
| PATCH | `/api/cards/{id}` | 编辑 |
| DELETE | `/api/cards/{id}` | 删除（级联清理 card_links） |

### 上传 / 反馈 / 设置 / 系统
| 方法 | 路径 | 说明 |
|------|------|------|
| POST | `/api/upload` | 多格式文档上传（TXT/MD/DOCX/PDF/图片） |
| POST | `/api/feedback` | 👍/👎 反馈 |
| GET/PUT | `/api/settings` | 运行设置 |
| GET/POST/PATCH/DELETE | `/api/ocr-models...` | OCR 模型管理 |
| GET/POST/PATCH/DELETE | `/api/folders...` | 监听文件夹管理 |
| GET | `/api/stats` | 统计 |
| GET | `/api/health` | 健康检查 |
| POST | `/api/system/scan` | 手动触发全量扫描 |
| POST | `/api/system/rebuild-links` | 重建链接 |
| POST | `/api/system/daily-summary` | 手动触发每日归纳 |
| POST | `/api/system/vacuum` | 数据库压缩 |

> 说明：`/api/stats` 与 `/api/health` 在 `stats.py` 和 `system.py` 中都有定义（重复但兼容）。

---

## 8. 环境配置

复制 `.env.example` 为 `.env`，关键变量：

| 变量 | 默认 | 说明 |
|------|------|------|
| `OPENAI_API_KEY` | （空） | 不填则 Demo 模式 |
| `OPENAI_BASE_URL` | `https://api.siliconflow.cn/v1` | OpenAI 兼容端点 |
| `LLM_MODEL` | `Pro/moonshotai/Kimi-K2.6` | 视觉 OCR 模型 |
| `QA_MODEL` | `deepseek-ai/DeepSeek-V3.2` | 纯文本问答模型 |
| `EMBEDDING_MODEL` | `BAAI/bge-m3` | 向量模型 |
| `EMBEDDING_DIM` | `1024` | 必须与模型一致 |
| `BAIDU_OCR_*` | （空） | 百度 OCR 可选 |
| `OCR_WORKERS` | `3` | OCR 后台并发 worker 数 |
| `OCR_PAGE_PARALLELISM` | `4` | 多页 PDF 并发页数 |
| `PDF_RENDER_ZOOM` | `1.5` | PDF 渲染缩放 |
| `LINK_ALPHA/BETA/GAMMA` | `0.6/0.3/0.1` | 链接权重三分量 |
| `LINK_WEIGHT_THRESHOLD` | `0.35` | 链接入图阈值 |
| `BRAIN_API_KEY` | （空） | API Key 认证（公网部署建议设置） |
| `UVICORN_WORKERS` | `1` | **请勿调高**（进程内状态，非多 worker 安全） |

---

## 9. 部署方式

### 方式一：Docker Compose（推荐）

```bash
cp .env.example .env   # 按需填 LLM Key
docker compose up -d --build
# 前端 http://localhost:8080，后端 http://localhost:8000
```

### 方式二：本地开发（热更新）

```bash
# 后端
cd backend && pip install -r requirements.txt && python main.py
# 前端（另开终端）
cd frontend && pnpm install && pnpm run dev   # :5173，代理 /api → :8000
```

### 方式三：生产 HTTPS

```bash
./scripts/deploy.sh --prod   # Caddy 自动申请 Let's Encrypt 证书
```

### 完整部署文档

见 [README.md](./README.md)，涵盖：本地/WSL、云服务器+HTTPS、裸金属 systemd、Syncthing 同步、数据备份等场景。

---

## 10. 运维指南

### 常用命令

| 操作 | 命令 |
|------|------|
| 一键部署 | `./scripts/deploy.sh` |
| 生产 HTTPS | `./scripts/deploy.sh --prod` |
| 查看日志 | `./scripts/deploy.sh --logs` 或 `docker compose logs -f backend` |
| 停止 | `./scripts/deploy.sh --stop` |
| 更新重启 | `./scripts/deploy.sh --update` |
| 备份数据库 | `./scripts/deploy.sh --backup` |
| 手动扫描 | `curl -X POST localhost:8000/api/system/scan` |
| 数据库压缩 | `curl -X POST localhost:8000/api/system/vacuum` |

### 数据备份

- SQLite 单文件 + 缩略图，整体在 `data/` 目录（已 .gitignore）
- `scripts/backup.sh` 生成 `data/backups/brain_YYYYMMDD_HHMMSS.db.gz`
- 建议 crontab 定时备份（见 README）

### 关键注意事项

1. **`UVICORN_WORKERS` 必须保持 1**：watcher / scheduler / 队列都是进程内状态，多 worker 会导致重复处理和状态错乱。并发靠 `OCR_WORKERS` 线程池，不靠多进程。
2. **OCR 依赖外部 LLM API**：本地不耗算力，但要留意 API 速率限制（RPM），过高并发会触发限流。
3. **`data/` 目录不在版本控制内**：数据库、同步笔记、缩略图都在本地 volume。
4. **多设备同步靠 Syncthing**：手机/平板装 Syncthing 客户端，同步到 `data/synced_notes/<子目录>`。

---

## 11. 最近变更记录

| 时间 | 变更 | 说明 |
|------|------|------|
| 2026-07 | 知识卡片 + 星云图谱 | 参考 Karpathy LLM Wiki「答案回写」模式，新增 knowledge_cards / card_links 表 + NebulaGraph 组件 + /cards 页面 |
| 2026-07 | 多格式文档上传 | 支持 TXT / Markdown / Word(.docx) |
| 2026-07 | 笔记删除功能 | UI + 后端软删除 |
| 2026-07 | OCR 并发优化 | 单 worker → 多 worker 线程池、多页 PDF 并发、链接重算异步化、client 复用 |
| 2026-07 | Docker 构建加速 | apt/pip 换清华源、corepack 走 npmmirror |

---

## 12. 已知问题与后续规划

### 已知限制 / 待办

1. **无向量数据库**：embedding 用内存余弦检索，数据量增大后（>1万篇）检索性能会下降，可迁移到 sqlite-vss / 独立向量库。
2. **卡片-笔记链接仅基于 citations**：尚未支持卡片间（card-to-card）的语义链接建立和手动编辑。
3. **无用户认证体系**：仅有可选的 `BRAIN_API_KEY` 静态认证，无多用户/登录。
4. **前端无 lint 门槛**：知识卡片功能落地时未加 lint 检查。
5. **Lint/测试**：项目整体缺少自动化测试（pytest / vitest）。

### 建议的后续方向

- 引入向量数据库提升检索规模
- 卡片间语义关联（知识网络自组织）
- 移动端简版（星云图谱在小屏体验一般）
- 补齐自动化测试与 CI

---

## 13. 交接检查清单

- [x] 源码完整（backend / frontend / scripts / docker 配置）
- [x] `.env.example` 环境变量模板齐全，真实 `.env` 已排除不进库
- [x] README 含部署 / 配置 / API / 运维文档
- [x] 本交接文档（架构 / 数据库 / API / 运维 / 已知问题）
- [x] 可快速启动：`docker compose up -d --build`

### 接手人需要的关键信息

| 项目 | 内容 |
|------|------|
| GitHub 仓库 | https://github.com/lxhb2/Brain.git |
| 主分支 | master |
| LLM 服务 | SiliconFlow（OpenAI 兼容），Key 在本地 `.env`（不入库） |
| 数据库 | SQLite，`data/brain.db`，本地 volume |
| 默认端口 | 前端 8080 / 后端 8000 |
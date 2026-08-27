# 从零搭建你的个人知识库应用：Brain 实操手册

> 这份文档写给想拥有自己「第二大脑」的人。它不是一个抽象的教程，而是 Brain 项目真实搭建、优化、踩坑和迭代的记录，你可以照着它一步步复刻，也可以直接改造这套代码。

## 一、这套系统解决什么问题

普通笔记软件只能“存”，不能“用”。Brain 的目标是：

1. 自动收集多设备笔记，不需要手动整理文件。
2. OCR 识别手写、PDF、图片，把内容变成可检索文本。
3. 用本地大模型做智能问答，回答时引用原始笔记。
4. 自动区分“实操经验”和“外部资料”，把真正验证过的方法沉淀下来。
5. 通过知识卡片、间隔复验、每日 AI 审核，形成“记录 → 调用 → 验证 → 改进”的正循环。

核心公式：`知识库价值 = 知识密度 × 调用频次 × 验证深度`。

## 二、系统由哪些部分组成

| 组件 | 技术 | 作用 |
| --- | --- | --- |
| 后端 | Python FastAPI | API、数据库、OCR 调度、问答、成长审核 |
| 前端 | React + Vite + React Flow | 笔记浏览、问答、图谱、成长面板 |
| 数据库 | SQLite | 笔记、问答、卡片、日志全部单文件存储 |
| 本地大模型 | LM Studio + Qwen3.5 4B | OCR 结构化、问答、分诊、审核 |
| 向量模型 | LM Studio + Nomic Embed | 笔记和记忆的语义向量 |
| 私有云盘 | SFTPGo | 手机/电脑上传文件 |
| 文件同步 | Syncthing | 多设备自动同步笔记目录 |
| 定时任务 | APScheduler | 扫描、备份、每日审核 |
| 反向代理 | Nginx | 前端托管 + API 转发 |

整套系统可以全部跑在本机，不依赖外部 API，数据完全私有。

## 三、架构图

```text
手机/平板/iPad/PC
      │
      ├── Syncthing ──► data/synced_notes/<device-app>/
      │
      └── Brain 网页 / SFTPGo ──► data/cloud/
                                    │
                        watcher 实时监听 + 每日扫描
                                    │
                              OCR + 向量化
                                    │
                    SQLite + 缩略图 + 图谱 + 成长分诊
                                    │
                    FastAPI(8000) ←─ Nginx(8080) ←─ 浏览器/PWA
```

## 四、搭建前的准备

推荐配置：

- Windows 10/11 或 Linux
- WSL2（Windows 上用）
- Docker Desktop
- 16 GB 内存（8 GB 也能跑，问答会慢一些）
- LM Studio
- 磁盘空间建议预留 10 GB 以上

模型：

- `qwen3.5-4b`：OCR 结构化、问答、分诊、每日审核
- `text-embedding-nomic-embed-text-v1.5`：768 维向量

## 五、第一次搭建

### 5.1 拉取项目

```bash
git clone https://github.com/lxhb2/Brain.git
cd Brain
```

### 5.2 安装 LM Studio 并加载模型

1. 打开 LM Studio。
2. 搜索并下载 `qwen3.5-4b`。
3. 搜索并下载 `text-embedding-nomic-embed-text-v1.5`。
4. 启动本地服务，端口保持 `1234`。
5. 确认访问：

```bash
curl http://127.0.0.1:1234/v1/models
```

### 5.3 配置环境变量

```bash
cp .env.example .env
```

编辑 `.env`，核心配置如下：

```env
OPENAI_API_KEY=lm-studio
OPENAI_BASE_URL=http://host.docker.internal:1234/v1
LLM_MODEL=qwen3.5-4b
QA_MODEL=qwen3.5-4b
EMBEDDING_MODEL=text-embedding-nomic-embed-text-v1.5
EMBEDDING_DIM=768
BRAIN_DATA_DIR=/home/lxhb/.local/var/brain
```

### 5.4 启动 Docker

```bash
cd Brain
docker compose up -d --build
```

启动后访问：

```text
http://localhost:8080
```

### 5.5 验证

```bash
curl http://localhost:8000/api/health
curl http://localhost:8000/api/stats
```

## 六、把数据放到自己的磁盘

默认数据在 `./data`，但项目目录可能被移动、清理或重新 clone，强烈建议把数据放到固定路径。

以 G 盘为例：

1. 在 Windows 上把 WSL 的虚拟磁盘 `ext4.vhdx` 移动到 `G:\WSL\Ubuntu-22.04\`。
2. 在 WSL 里创建固定目录：

```bash
mkdir -p /home/lxhb/.local/var/brain
rsync -aHAX ./data/ /home/lxhb/.local/var/brain/
```

3. 修改 `.env`：

```env
BRAIN_DATA_DIR=/home/lxhb/.local/var/brain
```

4. 重建容器：

```bash
docker compose up -d --force-recreate backend cloud syncthing
```

> 重要：不要把数据放到 `/mnt/c` 或 `/mnt/f` 这类 Windows 挂载路径上，性能和权限都不稳定。

## 七、局域网和手机访问

### 7.1 端口转发

WSL2 默认是 NAT 网络，Windows 物理机 IP 或 WSL IP 重启后可能变化。使用脚本自动刷新：

```powershell
powershell.exe -NoProfile -ExecutionPolicy Bypass `
  -File .\scripts\fix-wsl-portproxy.ps1 -RegisterTask
```

### 7.2 固定域名

安装 mDNS 广播：

```powershell
powershell.exe -NoProfile -ExecutionPolicy Bypass `
  -File .\scripts\register-brain-mdns.ps1
```

之后局域网内直接用：

```text
http://brain.local:8080
```

## 八、上传和自动入库

### 8.1 网页上传

主界面右上角点“上传”，支持：

- 图片：PNG / JPG，走 OCR
- PDF：走 OCR
- 文本：TXT / Markdown / DOCX，走文本抽取

上传后会保存到私有云盘目录，并立即进入处理队列。

### 8.2 云盘上传

访问 `http://brain.local:8090/web/client`，上传到 `from-brain` 目录，也会自动入库。

### 8.3 文件夹监听

以下目录出现新文件会自动处理：

```text
data/synced_notes/
├── ipad-goodnotes/
├── android-notes/
├── pc-onenote/
└── camera-shots/
data/cloud/
```

## 九、核心功能说明

### 9.1 入库分诊

每次笔记处理完成后，AI 判断：

- `practice`：你做过、验证过、有条件和结果
- `reference`：书、课程、别人的方法
- `noise`：寒暄、截图、临时信息

并提取：

```text
条件 → 动作 → 结果 → 证据 → 下一步
```

### 9.2 成长感知检索

问答排序：

```text
score = 0.70 × 语义相似度
      + 0.25 × 关键词重合
      + 成长加权
```

成长加权包括：

- `practice` +0.05
- 被正确复验卡片引用的笔记 +0.08
- 高频使用笔记 +0.032（封顶）
- `reference` -0.03

### 9.3 知识卡片

问答后自动生成卡片：

```text
标题
核心总结
关键结论
适用场景
检验问题
```

你回答检验问题后，系统判断掌握程度，并安排下次复验时间。

### 9.4 卡片复用

后续问答中如果答案引用了 `[卡片id]`，该卡片的 `use_count` +1，并记录 `last_used_at`。卡片列表、卡片详情、成长页都能看到复用次数。

### 9.5 每日成长审核

每天 23:05 自动执行：

1. 分诊少量未分类笔记。
2. 审核当天记录。
3. 生成：已沉淀、错题本、调整方案、复验问题。

## 十、我们讨论过的优化与决策

以下是 Brain 开发过程中真实讨论并落地的优化记录。

### 10.1 物理机 IP 改变后文档消失

**问题**：部署在 WSL，物理机 IP 改变后找不到原上传文件。

**原因**：数据依赖 Windows 挂载路径或项目目录，路径随环境变化。

**方案**：

- 把数据固定到 WSL 的 Linux 文件系统。
- 把虚拟磁盘放到 G 盘。
- 通过 `.env` 指定 `BRAIN_DATA_DIR`。
- 用 `brain.local` 和端口转发解决访问地址变化。

### 10.2 上传文件不自动进入知识库

**问题**：用户从网页上传文件后，还要手动复制到同步目录。

**方案**：

- 上传接口直接写入 `data/cloud/`。
- 写入后立即插入数据库并加入处理队列。
- watcher 继续按路径和哈希去重兜底。

### 10.3 手机找不到应用保存的文件

**问题**：手机 App 导出时看不到完整文件路径。

**方案**：

- 在 Brain 主界面提供上传按钮。
- 手机直接拍照或从系统分享菜单选择 Brain。
- 不再依赖用户寻找应用内部目录。

### 10.4 云盘要免费且长期可用

**方案**：使用开源 SFTPGo 自托管。

- 数据在自己磁盘上。
- 不依赖第三方云盘容量和隐私策略。
- 和 Brain 共用数据目录。

### 10.5 用本地模型替代云端 API

**问题**：调用外部 API 需要付费、可能限流、数据外流。

**方案**：

- 使用 LM Studio。
- 本地加载 Qwen3.5 4B 和 Nomic Embed。
- 容器通过 `host.docker.internal:1234` 访问。

### 10.6 OCR 失败

**问题**：初期 OCR 不稳定，出现空文本或乱码。

**方案**：

- 启用 JSON Schema 约束结构化输出。
- 提高 `max_tokens`。
- 兼容 Qwen 的 reasoning 输出。
- 失败自动重试，最多 3 次。

### 10.7 需要知道系统在干什么

**方案**：增加活动日志页面。

记录：

- 哪个模型完成什么任务
- 什么设备上传文件
- 什么时候备份
- 分诊、问答、审核结果

### 10.8 打开应用后看不到历史文档

**根因**：Docker Desktop 在 WSL 重启后，把绑定挂载降级成了 tmpfs 占位目录，后端每次重启都新建空数据库。

**方案**：

- 用探针文件验证容器能否读到真实数据目录。
- 检测失败自动 `force-recreate` 容器。
- 登录启动脚本最多重试 6 轮。
- 修复脚本：`scripts/ensure-brain-mount.ps1`。

### 10.9 知识库“存了很多但没长进”

**方案**：引入成长闭环。

- 入库分诊，只留活知识。
- 知识卡片 + 间隔复验。
- 每日 AI 审核。
- 成长页展示密度、调用、验证指标。

## 十一、踩坑清单

### 11.1 Docker Desktop tmpfs 假挂载

症状：容器里 `/app/data` 是 `tmpfs`，看不到真实数据库。

检查：

```bash
docker exec brain-backend sh -c "df -h /app/data"
```

修复：

```bash
docker compose up -d --force-recreate backend cloud syncthing
```

### 11.2 rsync 误删 `.env` 和运行数据

教训：同步代码时不要对整个项目目录执行 `rsync --delete`，尤其不要包含 `data/` 和 `.env`。

安全做法：

```bash
rsync -a --delete backend/ /home/lxhb/brain/backend/
rsync -a --delete frontend/src/ /home/lxhb/brain/frontend/src/
```

### 11.3 更换向量模型后维度不一致

不同嵌入模型输出维度不同，例如 BGE 是 1024，Nomic 是 768。维度不一致时余弦相似度返回 0，不会报错但查不到笔记。

换模型后必须：

```bash
备份数据库
重新生成所有笔记向量
重建关联边
```

### 11.4 Qwen 的 JSON 输出不稳定

解决：

- 使用 `response_format={"type": "json_schema"}`。
- 提高 `max_tokens`。
- 剥离 markdown 代码围栏。
- 兼容 `reasoning_content`。

## 十二、日常运营建议

每天花 10 分钟：

1. 把当天做过的、踩过的坑丢进 Brain。
2. 问它一次相关问题，让旧经验被调用。
3. 回答卡片上的检验问题。
4. 看成长页的错题本，挑一个明天能做的调整。

每周：

- 查看“调用广度”和“验证深度”。
- 把一直没被调用的卡片重新阅读或删掉。
- 把反复犯错的内容整理成“下次一定先做 X”的规则。

## 十三、下一步可以扩展的方向

1. 能力技能树：把经验自动归并成技能和熟练度。
2. 月度成长报告：最强技能、最弱技能、下月实验清单。
3. 执行提醒：把卡片的 `next_action` 变成待办提醒。
4. 多用户支持：家庭或团队共享知识库。
5. HTTPS + 公网访问：把系统部署到云服务器。

## 十四、相关文档

- [项目 README](../README.md)
- [运维手册](OPERATIONS.md)


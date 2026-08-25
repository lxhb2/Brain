#!/usr/bin/env bash
# Brain · SQLite 定时备份脚本
#
# 用途：在不停服的情况下备份 SQLite 数据库（用 .backup API 保证一致性）
# 推荐：配合 cron 每日执行
#
# 安装：
#   chmod +x scripts/backup.sh
#   crontab -e
#   # 每天凌晨 2 点备份
#   0 2 * * * /opt/brain/scripts/backup.sh >> /opt/brain/data/backups/cron.log 2>&1

set -euo pipefail

# ---- 配置 ----
PROJECT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
# 定时任务不会加载用户环境变量，这里从项目 .env 恢复配置
if [[ -f "${PROJECT_DIR}/.env" ]]; then
    env_data_dir="$(sed -n 's/^[[:space:]]*BRAIN_DATA_DIR=[[:space:]]*//p' "${PROJECT_DIR}/.env" | tail -n 1 | tr -d '\"' | tr -d "'")"
    [[ -n "$env_data_dir" ]] && export BRAIN_DATA_DIR="$env_data_dir"
fi
DATA_DIR="${BRAIN_DATA_DIR:-${PROJECT_DIR}/data}"
DB_PATH="${DATA_DIR}/brain.db"
BACKUP_DIR="${DATA_DIR}/backups"
KEEP_DAYS=14       # 本地保留 14 天
MAX_COPIES=14      # 最多保留 14 份

mkdir -p "$BACKUP_DIR"

# ---- 检查数据库 ----
if [[ ! -f "$DB_PATH" ]]; then
    echo "[$(date '+%Y-%m-%d %H:%M:%S')] ERROR: 数据库不存在 $DB_PATH"
    exit 1
fi

# ---- 生成备份 ----
TIMESTAMP=$(date +%Y%m%d_%H%M%S)
BACKUP_FILE="${BACKUP_DIR}/brain_${TIMESTAMP}.db"

# 优先用 sqlite3 命令（一致性最佳）
if command -v sqlite3 &>/dev/null; then
    sqlite3 "$DB_PATH" ".backup '$BACKUP_FILE'"
elif command -v python3 &>/dev/null; then
    # 退而求其次：用 Python 的 sqlite3 模块
    python3 -c "
import sqlite3
src = sqlite3.connect('${DB_PATH}')
dst = sqlite3.connect('${BACKUP_FILE}')
src.backup(dst)
dst.close()
src.close()
"
else
    # 最后兜底：直接复制（可能有不一致风险，但 SQLite 单文件通常 OK）
    cp "$DB_PATH" "$BACKUP_FILE"
fi

# 压缩节省空间
gzip -f "$BACKUP_FILE"

echo "[$(date '+%Y-%m-%d %H:%M:%S')] OK: 已备份 ${BACKUP_FILE}.gz ($(du -h "${BACKUP_FILE}.gz" | cut -f1))"

# ---- 清理旧备份 ----
find "$BACKUP_DIR" -name "brain_*.db.gz" -mtime +${KEEP_DAYS} -delete 2>/dev/null || true
# 同时按数量限制（防止每天多次备份导致文件过多）
ls -t "$BACKUP_DIR"/brain_*.db.gz 2>/dev/null | tail -n +$((MAX_COPIES + 1)) | xargs -r rm

echo "[$(date '+%Y-%m-%d %H:%M:%S')] INFO: 当前备份目录共 $(ls -1 "$BACKUP_DIR"/brain_*.db.gz 2>/dev/null | wc -l) 份"

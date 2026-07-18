#!/usr/bin/env bash
# Brain · 一键部署脚本（WSL / Linux 云服务器通用）
#
# 用法：
#   chmod +x scripts/deploy.sh
#   ./scripts/deploy.sh              # 默认部署（HTTP，端口 8080）
#   ./scripts/deploy.sh --prod        # 生产部署（HTTPS，需先改 Caddyfile 域名）
#   ./scripts/deploy.sh --sync        # 同时启动 Syncthing 同步
#   ./scripts/deploy.sh --update      # 拉取最新代码并重新构建
#   ./scripts/deploy.sh --logs        # 查看日志
#   ./scripts/deploy.sh --stop        # 停止服务
#   ./scripts/deploy.sh --backup      # 立即备份数据库
#
# 适合小白：脚本会自动检查 Docker、创建 .env、初始化目录

set -euo pipefail

# ---- 颜色输出 ----
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m'

info()  { echo -e "${GREEN}[INFO]${NC}  $*"; }
warn()  { echo -e "${YELLOW}[WARN]${NC}  $*"; }
error() { echo -e "${RED}[ERROR]${NC} $*"; }
step()  { echo -e "${BLUE}[STEP]${NC}  $*"; }

# ---- 项目根目录 ----
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_DIR="$(cd "$SCRIPT_DIR/.." && pwd)"
cd "$PROJECT_DIR"

# ---- 参数解析 ----
MODE="dev"
ACTION="up"
SYNC=false
while [[ $# -gt 0 ]]; do
    case "$1" in
        --prod)   MODE="prod"; shift ;;
        --sync)   SYNC=true;  shift ;;
        --update) ACTION="update"; shift ;;
        --logs)   ACTION="logs"; shift ;;
        --stop)   ACTION="stop"; shift ;;
        --backup) ACTION="backup"; shift ;;
        --help|-h)
            cat <<EOF
Brain 部署脚本
用法: ./scripts/deploy.sh [选项]
  (无参数)    开发部署（HTTP，端口 8080）
  --prod      生产部署（HTTPS + Caddy，需先改 Caddyfile）
  --sync      同时启动 Syncthing 笔记同步
  --update    拉取最新代码并重新构建
  --logs      查看实时日志
  --stop      停止所有服务
  --backup    立即备份 SQLite 数据库
  --help      显示此帮助
EOF
            exit 0 ;;
        *) error "未知参数: $1"; exit 1 ;;
    esac
done

# ---- 检查 Docker ----
check_docker() {
    if ! command -v docker &>/dev/null; then
        error "未检测到 Docker，正在尝试自动安装..."
        step "安装 Docker（需要 sudo 权限）"
        curl -fsSL https://get.docker.com | sudo sh
        sudo systemctl enable --now docker
        sudo usermod -aG docker "$USER"
        warn "请重新登录以使 docker 组生效，或用 sudo 运行本脚本"
        exit 0
    fi
    if ! docker compose version &>/dev/null; then
        error "未检测到 docker compose 插件，请安装 Docker Compose V2"
        exit 1
    fi
    info "Docker 已就绪: $(docker --version)"
}

# ---- 初始化 .env ----
init_env() {
    if [[ ! -f .env ]]; then
        step "创建 .env 配置文件"
        cp .env.example .env
        info "已创建 .env（默认 Demo 模式，无需 API Key 也能跑）"
        echo ""
        warn "要启用真实 OCR/问答？编辑 .env 填入 OPENAI_API_KEY，然后执行：./scripts/deploy.sh --update"
        echo ""
    fi
}

# ---- 初始化目录 ----
init_dirs() {
    step "创建数据目录"
    mkdir -p data/synced_notes/{ipad-goodnotes,android-notes,pc-onenote,camera-shots}
    mkdir -p data/thumbnails
    mkdir -p data/backups
    info "数据目录就绪: $(pwd)/data/"
}

# ---- 启动服务 ----
start_services() {
    local compose_args=(-d --build)
    if $SYNC; then
        compose_args+=(--profile sync)
    fi

    if [[ "$MODE" == "prod" ]]; then
        step "生产模式启动（Caddy HTTPS）"
        if grep -q "brain.example.com" Caddyfile; then
            error "请先编辑 Caddyfile，把 brain.example.com 改成你的真实域名"
            echo "    nano Caddyfile"
            exit 1
        fi
        docker compose -f docker-compose.yml -f docker-compose.prod.yml up "${compose_args[@]}"
    else
        step "开发模式启动（HTTP :8080）"
        docker compose up "${compose_args[@]}"
    fi

    echo ""
    info "✅ 部署完成"
    if [[ "$MODE" == "prod" ]]; then
        echo "    访问: https://$(grep -oP '^[a-z0-9.]+' Caddyfile | head -1)"
    else
        echo "    访问: http://$(hostname -I 2>/dev/null | awk '{print $1}' || echo localhost):8080"
        echo "    后端: http://$(hostname -I 2>/dev/null | awk '{print $1}' || echo localhost):8000"
    fi
    echo ""
    echo "    查看日志:   ./scripts/deploy.sh --logs"
    echo "    停止服务:   ./scripts/deploy.sh --stop"
    echo "    备份数据库: ./scripts/deploy.sh --backup"
}

# ---- 更新 ----
do_update() {
    step "拉取最新代码"
    git pull --rebase 2>/dev/null || warn "非 git 仓库或拉取失败，跳过"
    step "重新构建并启动"
    start_services
}

# ---- 查看日志 ----
show_logs() {
    docker compose logs -f --tail=100
}

# ---- 停止 ----
do_stop() {
    step "停止所有服务"
    if [[ "$MODE" == "prod" ]]; then
        docker compose -f docker-compose.yml -f docker-compose.prod.yml down
    else
        docker compose down
    fi
    info "已停止"
}

# ---- 备份 ----
do_backup() {
    step "备份 SQLite 数据库"
    local ts backup_file
    ts=$(date +%Y%m%d_%H%M%S)
    backup_file="data/backups/brain_${ts}.db"
    if [[ -f data/brain.db ]]; then
        # 用 sqlite3 的 backup API 保证一致性（无需停服）
        docker compose exec -T backend python -c \
            "import sqlite3; src=sqlite3.connect('/app/data/brain.db'); dst=sqlite3.connect('/app/data/backups/brain_${ts}.db'); src.backup(dst); dst.close(); src.close()" \
            2>/dev/null || cp data/brain.db "$backup_file"
        info "已备份: $backup_file"
        # 仅保留最近 14 份
        ls -t data/backups/brain_*.db 2>/dev/null | tail -n +15 | xargs -r rm
        info "已清理旧备份（保留最近 14 份）"
    else
        warn "未找到 data/brain.db，跳过备份"
    fi
}

# ---- 主流程 ----
main() {
    info "Brain 部署脚本 · 模式: $MODE"
    info "项目目录: $PROJECT_DIR"

    case "$ACTION" in
        up)      check_docker; init_env; init_dirs; start_services ;;
        update)  check_docker; do_update ;;
        logs)    show_logs ;;
        stop)    do_stop ;;
        backup)  do_backup ;;
    esac
}

main

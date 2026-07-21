"""Brain 后端 FastAPI 入口。

启动时：
  - init_db()
  - 重置僵尸 processing 任务为 pending（崩溃恢复）
  - start_worker()  后台 OCR worker
  - start_watcher() 文件监听
  - start_scheduler() 定时全量扫描 + 每日归纳 + 记忆衰减
若 ../frontend/dist 存在，则挂载静态文件托管前端。

安全：
  - 若环境变量 BRAIN_API_KEY 设置，则所有 /api/* 请求必须带
    `X-API-Key: <key>` header（或 ?api_key=<key> query）。
  - 未设置则不启用认证（兼容本地单机使用）。
"""
from __future__ import annotations

import logging
import os
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from starlette.middleware.base import BaseHTTPMiddleware

from config import get_config
from database import init_db, reset_stale_processing_notes
from routes import feedback as feedback_routes
from routes import graph as graph_routes
from routes import notes as notes_routes
from routes import qa as qa_routes
from routes import settings as settings_routes
from routes import stats as stats_routes
from routes import system as system_routes
from routes import upload as upload_routes
from routes import cards as cards_routes
from scheduler import start_scheduler, start_worker, stop_scheduler, stop_worker
from watcher import start_watcher, stop_watcher

logging.basicConfig(
    level=os.environ.get("LOG_LEVEL", "INFO"),
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger("brain.main")

# 认证开关：环境变量 BRAIN_API_KEY 设置则启用
_API_KEY = os.environ.get("BRAIN_API_KEY", "").strip()
# 健康检查路径白名单（始终免认证）
_PUBLIC_PATHS = {"/api/health"}


class ApiKeyMiddleware(BaseHTTPMiddleware):
    """简单的 X-API-Key 认证中间件。

    - /api/health 始终放行（健康检查）
    - 非 /api/* 路径放行（静态资源）
    - 若未配置 BRAIN_API_KEY 则全部放行（本地模式）
    """

    async def dispatch(self, request: Request, call_next):
        if not _API_KEY:
            return await call_next(request)
        path = request.url.path
        # 静态资源 / 根路径 / 健康检查放行
        if not path.startswith("/api/") or path in _PUBLIC_PATHS:
            return await call_next(request)
        # 从 header 或 query 读取 key
        provided = request.headers.get("X-API-Key") or request.query_params.get("api_key") or ""
        if provided != _API_KEY:
            return JSONResponse(
                status_code=401,
                content={"detail": "无效或缺失的 API Key"},
            )
        return await call_next(request)


@asynccontextmanager
async def lifespan(app: FastAPI):
    """应用生命周期：启动后台服务 + 优雅关闭。"""
    logger.info("Brain 启动中...")
    init_db()

    # 崩溃恢复：把上次崩溃时 status='processing' 的笔记重置为 pending
    try:
        reset_count = reset_stale_processing_notes()
        if reset_count > 0:
            logger.info("崩溃恢复：重置 %s 个僵尸 processing 任务为 pending", reset_count)
    except Exception as e:
        logger.warning("崩溃恢复失败: %s", e)

    start_worker()
    try:
        start_watcher()
    except Exception as e:
        logger.warning("watcher 启动失败（不阻断启动）: %s", e)
    try:
        start_scheduler()
    except Exception as e:
        logger.warning("scheduler 启动失败（不阻断启动）: %s", e)

    if _API_KEY:
        logger.info("API Key 认证已启用")
    else:
        logger.warning("未配置 BRAIN_API_KEY，API 无认证保护（仅适合本地单机使用）")

    logger.info("Brain 启动完成")
    yield

    # 优雅关闭
    logger.info("Brain 关闭中...")
    try:
        stop_scheduler()
    except Exception as e:
        logger.warning("停止 scheduler 失败: %s", e)
    try:
        stop_worker()
    except Exception as e:
        logger.warning("停止 worker 失败: %s", e)
    try:
        stop_watcher()
    except Exception as e:
        logger.warning("停止 watcher 失败: %s", e)
    logger.info("Brain 已关闭")


def create_app() -> FastAPI:
    """构造 FastAPI 应用。"""
    app = FastAPI(
        title="Brain API",
        description="个人手写笔记知识图谱后端",
        version="0.1.0",
        lifespan=lifespan,
    )

    # CORS：allow_origins=["*"] 与 allow_credentials=True 不能同时为真
    # （浏览器规范）。这里默认本地单机用，allow_credentials=False。
    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],
        allow_credentials=False,
        allow_methods=["*"],
        allow_headers=["*"],
    )
    # API Key 认证（仅当配置了 BRAIN_API_KEY 时生效）
    app.add_middleware(ApiKeyMiddleware)

    # 注册路由
    app.include_router(notes_routes.router)
    app.include_router(graph_routes.router)
    app.include_router(qa_routes.router)
    app.include_router(feedback_routes.router)
    app.include_router(stats_routes.router)
    app.include_router(settings_routes.router)
    app.include_router(system_routes.router)
    app.include_router(upload_routes.router)
    app.include_router(cards_routes.router)

    # 根路径重定向到图谱页
    @app.get("/", include_in_schema=False)
    def root():
        return RedirectResponse(url="/graph")

    # 前端静态托管
    frontend_dist = os.path.join(os.path.dirname(__file__), "..", "frontend", "dist")
    frontend_dist = os.path.normpath(frontend_dist)
    if os.path.isdir(frontend_dist):
        # /graph /qa /notes 等前端路由由 index.html 接管
        app.mount(
            "/",
            StaticFiles(directory=frontend_dist, html=True),
            name="frontend",
        )
        logger.info("已挂载前端静态目录: %s", frontend_dist)
    else:
        logger.info("未发现前端构建目录 %s，仅提供 API", frontend_dist)

    return app


app = create_app()


if __name__ == "__main__":
    import uvicorn

    uvicorn.run("main:app", host="0.0.0.0", port=8000, reload=False)

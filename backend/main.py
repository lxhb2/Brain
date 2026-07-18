"""Brain 后端 FastAPI 入口。

启动时：
  - init_db()
  - start_worker()  后台 OCR worker
  - start_watcher() 文件监听
  - start_scheduler() 定时全量扫描
若 ../frontend/dist 存在，则挂载静态文件托管前端。
"""
from __future__ import annotations

import logging
import os
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import RedirectResponse
from fastapi.staticfiles import StaticFiles

from config import get_config
from database import init_db
from routes import feedback as feedback_routes
from routes import graph as graph_routes
from routes import notes as notes_routes
from routes import qa as qa_routes
from routes import settings as settings_routes
from routes import stats as stats_routes
from routes import system as system_routes
from routes import upload as upload_routes
from scheduler import start_scheduler, start_worker
from watcher import start_watcher

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger("brain.main")


@asynccontextmanager
async def lifespan(app: FastAPI):
    """应用生命周期：启动后台服务。"""
    logger.info("Brain 启动中...")
    init_db()
    start_worker()
    try:
        start_watcher()
    except Exception as e:
        logger.warning("watcher 启动失败（不阻断启动）: %s", e)
    try:
        start_scheduler()
    except Exception as e:
        logger.warning("scheduler 启动失败（不阻断启动）: %s", e)
    logger.info("Brain 启动完成")
    yield
    logger.info("Brain 关闭中...")


def create_app() -> FastAPI:
    """构造 FastAPI 应用。"""
    app = FastAPI(
        title="Brain API",
        description="个人手写笔记知识图谱后端",
        version="0.1.0",
        lifespan=lifespan,
    )

    # CORS 全部放开（本地/局域网单用户系统）
    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    # 注册路由
    app.include_router(notes_routes.router)
    app.include_router(graph_routes.router)
    app.include_router(qa_routes.router)
    app.include_router(feedback_routes.router)
    app.include_router(stats_routes.router)
    app.include_router(settings_routes.router)
    app.include_router(system_routes.router)
    app.include_router(upload_routes.router)

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

"""系统状态与统计 API 路由。"""
from __future__ import annotations

from fastapi import APIRouter

import database
from config import get_config

router = APIRouter(prefix="/api", tags=["stats"])


@router.get("/stats")
def stats():
    """返回仪表盘统计信息。"""
    return database.get_stats()


@router.get("/health")
def health():
    """健康检查。"""
    cfg = get_config()
    return {
        "status": "ok",
        "openai_configured": bool(cfg.OPENAI_API_KEY),
        "llm_model": cfg.LLM_MODEL,
        "embedding_model": cfg.EMBEDDING_MODEL,
    }

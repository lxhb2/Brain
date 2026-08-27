"""系统状态与统计 API 路由。"""
from __future__ import annotations

from fastapi import APIRouter

import database

router = APIRouter(prefix="/api", tags=["stats"])


@router.get("/stats")
def stats():
    """返回仪表盘统计信息。"""
    return database.get_stats()



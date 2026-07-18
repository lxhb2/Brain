"""图谱相关 API 路由。"""
from __future__ import annotations

from typing import Optional

from fastapi import APIRouter, Query

import graph_api

router = APIRouter(prefix="/api/graph", tags=["graph"])


@router.get("")
def get_graph(
    device: Optional[str] = Query(None),
    app: Optional[str] = Query(None),
    q: Optional[str] = Query(None),
    status: Optional[str] = Query(None),
):
    """返回图谱节点与边，支持筛选。"""
    filters = {"device": device, "app": app, "q": q, "status": status}
    # 过滤掉 None 值
    filters = {k: v for k, v in filters.items() if v is not None}
    return graph_api.get_graph(filters)


@router.get("/neighbors/{note_id}")
def get_neighbors(note_id: int):
    """返回某节点的邻居节点与边。"""
    return graph_api.get_neighbors(note_id)

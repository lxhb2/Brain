"""问答相关 API 路由。"""
from __future__ import annotations

from typing import Optional

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel, Field

import database
import qa_engine

router = APIRouter(prefix="/api/qa", tags=["qa"])


class AskRequest(BaseModel):
    """问答请求体。"""

    question: str = Field(..., min_length=1)
    session_id: Optional[str] = None  # 会话 ID，用于多轮对话


@router.post("/ask")
def ask(req: AskRequest):
    """对用户问题执行 RAG 问答。

    - 可传 session_id 支持多轮对话（同 session 的最近 5 轮历史会注入 prompt）
    - 自动检索 user_memory 长期记忆并注入 prompt
    """
    return qa_engine.ask(req.question, session_id=req.session_id)


@router.get("/history")
def history(
    limit: int = Query(50, ge=1, le=1000),
    offset: int = Query(0, ge=0),
    session_id: Optional[str] = Query(None),
):
    """返回问答历史。可按 session_id 过滤。"""
    return {"items": qa_engine.get_history(limit=limit, offset=offset, session_id=session_id)}


# ---------------------------------------------------------------------------
# 长期记忆管理
# ---------------------------------------------------------------------------
class MemoryCreate(BaseModel):
    """新增记忆请求。"""
    type: str = Field(..., description="preference / fact / correction / term")
    content: str = Field(..., min_length=1)
    weight: float = Field(0.5, ge=0.0, le=1.0)


class MemoryUpdate(BaseModel):
    """更新记忆请求。"""
    content: Optional[str] = None
    weight: Optional[float] = Field(None, ge=0.0, le=1.0)
    type: Optional[str] = None


@router.get("/memories")
def list_memories(
    type: Optional[str] = Query(None),
    limit: int = Query(100, ge=1, le=500),
    offset: int = Query(0, ge=0),
):
    """列出长期记忆。可按 type 过滤。"""
    items = database.list_memory(type=type, limit=limit, offset=offset)
    return {"items": items, "total": len(items)}


@router.post("/memories")
def add_memory(body: MemoryCreate):
    """手动添加一条长期记忆。"""
    if body.type not in ("preference", "fact", "correction", "term"):
        raise HTTPException(400, "type 必须是 preference/fact/correction/term")
    memory_id = qa_engine.add_manual_memory(body.type, body.content, body.weight)
    return {"memory_id": memory_id, "memory": database.get_memory(memory_id)}


@router.patch("/memories/{memory_id}")
def update_memory(memory_id: int, body: MemoryUpdate):
    """更新记忆字段。"""
    if not database.get_memory(memory_id):
        raise HTTPException(404, "记忆不存在")
    database.update_memory(
        memory_id,
        content=body.content,
        weight=body.weight,
        type=body.type,
    )
    return {"memory_id": memory_id, "memory": database.get_memory(memory_id)}


@router.delete("/memories/{memory_id}")
def delete_memory(memory_id: int):
    """删除一条记忆。"""
    ok = database.delete_memory(memory_id)
    if not ok:
        raise HTTPException(404, "记忆不存在")
    return {"deleted": True, "memory_id": memory_id}

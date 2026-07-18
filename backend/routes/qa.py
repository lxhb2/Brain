"""问答相关 API 路由。"""
from __future__ import annotations

from fastapi import APIRouter, Query
from pydantic import BaseModel, Field

import qa_engine

router = APIRouter(prefix="/api/qa", tags=["qa"])


class AskRequest(BaseModel):
    """问答请求体。"""

    question: str = Field(..., min_length=1)


@router.post("/ask")
def ask(req: AskRequest):
    """对用户问题执行 RAG 问答。"""
    return qa_engine.ask(req.question)


@router.get("/history")
def history(limit: int = Query(50, ge=1, le=1000), offset: int = Query(0, ge=0)):
    """返回问答历史。"""
    return {"items": qa_engine.get_history(limit=limit, offset=offset)}

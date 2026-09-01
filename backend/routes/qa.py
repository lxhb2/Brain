"""问答相关 API 路由。"""
from __future__ import annotations

from typing import Optional

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel, Field

import database
import qa_engine
import web_research

router = APIRouter(prefix="/api/qa", tags=["qa"])


class AskRequest(BaseModel):
    """问答请求体。"""

    question: str = Field(..., min_length=1)
    session_id: Optional[str] = None  # 会话 ID，用于多轮对话


@router.post("/ask")
def ask(req: AskRequest):
    """对用户问题执行 RAG 问答（轻量 Agent）。

    - 可传 session_id 支持多轮对话（同 session 的最近 5 轮历史会注入 prompt）
    - 自动检索 user_memory 长期记忆并注入 prompt
    - LLM 可主动调 search_notes / search_memory / add_memory 工具
    """
    return qa_engine.ask(req.question, session_id=req.session_id)


class CardDraftRequest(BaseModel):
    """基于一条已有问答生成可编辑卡片草稿。"""

    qa_id: int


@router.post("/card-draft")
def create_card_draft(req: CardDraftRequest):
    """手动把任意一条 AI 回答转换成知识卡片草稿。"""
    try:
        draft = qa_engine.generate_card_draft_for_qa(req.qa_id)
    except ValueError as exc:
        raise HTTPException(404, str(exc))
    except Exception as exc:
        raise HTTPException(500, f"知识卡片草稿生成失败：{exc}")
    if not draft:
        raise HTTPException(502, "知识卡片草稿生成失败，请稍后重试")
    return {"card_draft": draft}


class ResearchRequest(BaseModel):
    """基于已有回答或自定义观点生成验证 / 辩论报告。"""

    qa_id: int
    mode: str = "verify"
    statement: Optional[str] = None


@router.post("/research")
def research(req: ResearchRequest):
    """生成临时联网验证报告。结果不会写入笔记库。"""
    if req.mode not in ("verify", "debate"):
        raise HTTPException(400, "mode 必须是 verify 或 debate")
    qa = database.get_qa(req.qa_id)
    if not qa:
        raise HTTPException(404, "问答记录不存在")
    try:
        return web_research.research(
            mode=req.mode,
            statement=req.statement,
            question=qa.get("question"),
            answer=str(qa.get("answer") or ""),
            citations=qa.get("citations") or [],
        )
    except ValueError as exc:
        raise HTTPException(400, str(exc))
    except Exception as exc:
        raise HTTPException(500, f"联网报告生成失败：{exc}")


@router.get("/history")
def history(
    limit: int = Query(50, ge=1, le=1000),
    offset: int = Query(0, ge=0),
    session_id: Optional[str] = Query(None),
):
    """返回问答历史。可按 session_id 过滤。"""
    return {"items": qa_engine.get_history(limit=limit, offset=offset, session_id=session_id)}


# ---------------------------------------------------------------------------
# 会话管理
# ---------------------------------------------------------------------------
class SessionRenameRequest(BaseModel):
    """会话重命名请求。"""

    title: str = Field(..., min_length=1, max_length=60)


@router.get("/sessions")
def list_sessions(limit: int = Query(50, ge=1, le=200)):
    """列出所有会话，按 updated_at 倒序。"""
    items = qa_engine.list_sessions(limit=limit)
    return {"items": items, "total": len(items)}


@router.patch("/sessions/{session_id}")
def rename_session(session_id: str, body: SessionRenameRequest):
    """重命名会话标题。"""
    ok = qa_engine.rename_session(session_id, body.title)
    if not ok:
        raise HTTPException(404, "会话不存在")
    return {"session_id": session_id, "title": body.title}


@router.delete("/sessions/{session_id}")
def delete_session(session_id: str):
    """删除会话及其所有问答记录。"""
    ok = qa_engine.delete_session(session_id)
    if not ok:
        raise HTTPException(404, "会话不存在")
    return {"deleted": True, "session_id": session_id}


# ---------------------------------------------------------------------------
# 长期记忆管理
# ---------------------------------------------------------------------------
class MemoryCreate(BaseModel):
    """新增记忆请求。"""

    type: str = Field(..., description="preference / fact / correction / term / ocr_correction / ocr_addition")
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
    if body.type not in ("preference", "fact", "correction", "term", "ocr_correction", "ocr_addition"):
        raise HTTPException(400, "type 必须是 preference/fact/correction/term/ocr_correction/ocr_addition")
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

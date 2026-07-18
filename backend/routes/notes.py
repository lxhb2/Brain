"""笔记相关 API 路由。"""
from __future__ import annotations

import os
from typing import Optional

from fastapi import APIRouter, HTTPException, Query
from fastapi.responses import FileResponse

import database
import scheduler
from config import get_config

router = APIRouter(prefix="/api/notes", tags=["notes"])


@router.get("")
def list_notes(
    device: Optional[str] = Query(None),
    app: Optional[str] = Query(None),
    q: Optional[str] = Query(None),
    status: Optional[str] = Query(None),
    limit: int = Query(50, ge=1, le=10000),
    offset: int = Query(0, ge=0),
):
    """笔记列表，支持 device/app/q/status/limit/offset 筛选。"""
    items = database.list_notes(
        device=device, app=app, q=q, status=status, limit=limit, offset=offset
    )
    total = database.count_notes(status=status)
    return {"items": items, "total": total, "limit": limit, "offset": offset}


@router.get("/{note_id}")
def get_note(note_id: int):
    """获取单条笔记详情。"""
    note = database.get_note(note_id)
    if not note:
        raise HTTPException(status_code=404, detail="笔记不存在")
    return note


@router.get("/{note_id}/file")
def get_note_file(note_id: int):
    """返回笔记原始文件流。"""
    note = database.get_note(note_id)
    if not note:
        raise HTTPException(status_code=404, detail="笔记不存在")
    file_path = note.get("file_path") or ""
    if not file_path or not os.path.exists(file_path):
        raise HTTPException(status_code=404, detail="原始文件不存在")
    return FileResponse(file_path, filename=os.path.basename(file_path))


@router.get("/{note_id}/thumbnail")
def get_note_thumbnail(note_id: int):
    """返回缩略图；若缺失则回退到原始文件。"""
    note = database.get_note(note_id)
    if not note:
        raise HTTPException(status_code=404, detail="笔记不存在")
    thumb = note.get("thumbnail_path")
    if thumb and os.path.exists(thumb):
        return FileResponse(thumb, media_type="image/jpeg")
    # 回退：返回原始文件
    file_path = note.get("file_path") or ""
    if file_path and os.path.exists(file_path):
        return FileResponse(file_path)
    raise HTTPException(status_code=404, detail="缩略图与原始文件均不存在")


@router.post("/reprocess/{note_id}")
def reprocess_note(note_id: int):
    """重新触发某条笔记的 OCR 处理。"""
    note = database.get_note(note_id)
    if not note:
        raise HTTPException(status_code=404, detail="笔记不存在")
    database.update_note_status(note_id, "pending")
    scheduler.enqueue_note(note_id)
    return {"note_id": note_id, "status": "pending", "queued": True}

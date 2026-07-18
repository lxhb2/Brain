"""笔记相关 API 路由。"""
from __future__ import annotations

import os
from typing import Optional

from fastapi import APIRouter, HTTPException, Query
from fastapi.responses import FileResponse
from pydantic import BaseModel

import database
import ocr_processor
import scheduler
import settings_store
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


class ReOcrRequest(BaseModel):
    """用指定模型重新 OCR。"""
    model_id: Optional[str] = None  # None 表示用 primary


@router.post("/{note_id}/reocr")
def reocr_note(note_id: int, body: ReOcrRequest):
    """用指定模型对笔记重新 OCR（同步调用，等待结果）。

    - 不指定 model_id 则用 primary 模型
    - 指定的 model_id 必须存在于 settings_store.ocr_models 中
    - OCR 完成后立即返回新内容（不进入队列，前端可立即看到结果）
    """
    note = database.get_note(note_id)
    if not note:
        raise HTTPException(status_code=404, detail="笔记不存在")
    file_path = note.get("file_path") or ""
    if not file_path or not os.path.exists(file_path):
        raise HTTPException(status_code=404, detail="原始文件不存在")

    # 校验 model_id（如果指定）
    if body.model_id:
        m = settings_store.get_ocr_model_by_id(body.model_id)
        if not m:
            raise HTTPException(status_code=400, detail=f"OCR 模型 {body.model_id} 不存在")

    # 同步处理（前端会显示 loading）
    database.update_note_status(note_id, "processing")
    ok = ocr_processor.process_note(note_id, model_id=body.model_id)
    if not ok:
        raise HTTPException(status_code=500, detail="OCR 失败，请查看后端日志")

    updated = database.get_note(note_id)
    return {
        "note_id": note_id,
        "status": updated.get("status") if updated else "done",
        "ocr_model": updated.get("ocr_model") if updated else None,
        "title": updated.get("title") if updated else None,
        "ocr_text": updated.get("ocr_text") if updated else None,
        "summary": updated.get("summary") if updated else None,
        "keywords": updated.get("keywords") if updated else [],
    }

"""笔记相关 API 路由。"""
from __future__ import annotations

import os
from typing import Any, List, Optional

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
    """返回笔记原始文件流。显式指定 Content-Type 以支持浏览器内嵌预览（PDF/图片）。"""
    note = database.get_note(note_id)
    if not note:
        raise HTTPException(status_code=404, detail="笔记不存在")
    file_path = note.get("file_path") or ""
    if not file_path or not os.path.exists(file_path):
        raise HTTPException(status_code=404, detail="原始文件不存在")
    # 根据扩展名显式指定 media_type，避免移动端 Chrome 把 PDF 当下载
    ext = os.path.splitext(file_path)[1].lower()
    media_type = {
        ".pdf": "application/pdf",
        ".png": "image/png",
        ".jpg": "image/jpeg",
        ".jpeg": "image/jpeg",
    }.get(ext, "application/octet-stream")
    headers = {
        # 允许浏览器内嵌展示（iframe / img），避免某些代理附加下载头
        "Content-Disposition": f"inline; filename=\"{os.path.basename(file_path)}\""
    }
    return FileResponse(file_path, media_type=media_type, filename=os.path.basename(file_path), headers=headers)


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


class EditNoteRequest(BaseModel):
    """人工编辑笔记字段。所有字段可选，只更新传入的。"""
    title: Optional[str] = None
    ocr_text: Optional[str] = None
    summary: Optional[str] = None
    keywords: Optional[List[str]] = None
    recompute_embedding: bool = True  # 是否同步重算 embedding 和链接


@router.patch("/{note_id}")
def edit_note(note_id: int, body: EditNoteRequest):
    """人工编辑笔记的 OCR 文本/标题/摘要/关键词。

    - 标记 manually_edited=1，后续重新 OCR 不会覆盖人工修改
    - 默认重算 embedding 和候选链接（保持图谱同步）
    - 若不需要重算（例如只改 typo），传 recompute_embedding=False
    """
    note = database.get_note(note_id)
    if not note:
        raise HTTPException(status_code=404, detail="笔记不存在")

    # 收集要更新的字段
    updates = {}
    if body.title is not None:
        updates["title"] = body.title.strip()
    if body.ocr_text is not None:
        updates["ocr_text"] = body.ocr_text
    if body.summary is not None:
        updates["summary"] = body.summary.strip()
    if body.keywords is not None:
        updates["keywords"] = [k.strip() for k in body.keywords if k.strip()]
    updates["manually_edited"] = True

    if not any(k != "manually_edited" for k in updates):
        raise HTTPException(status_code=400, detail="未提供任何要更新的字段")

    # 写入数据库（先不更新 embedding）
    database.update_note_fields(
        note_id,
        title=updates.get("title"),
        ocr_text=updates.get("ocr_text"),
        summary=updates.get("summary"),
        keywords=updates.get("keywords"),
        manually_edited=True,
    )

    # 重算 embedding 和链接
    embedding_info = {"recomputed": False, "error": None}
    if body.recompute_embedding:
        try:
            client = ocr_processor._get_client()
            if client is None:
                embedding_info["error"] = "demo 模式，未重算"
            else:
                updated_note = database.get_note(note_id)
                embed_input = (
                    (updated_note.get("title") or "")
                    + "\n"
                    + (updated_note.get("summary") or "")
                    + "\n"
                    + (updated_note.get("ocr_text") or "")
                )
                emb = ocr_processor._embed_text(client, embed_input)
                database.update_note_fields(note_id, embedding=emb)
                # 重算链接
                try:
                    import graph_api
                    graph_api.recompute_links_for_note(note_id)
                except Exception as ge:
                    embedding_info["error"] = f"链接重算失败: {ge}"
                embedding_info["recomputed"] = True
        except Exception as e:
            embedding_info["error"] = str(e)

    return {
        "note_id": note_id,
        "updated": True,
        "manually_edited": True,
        "embedding": embedding_info,
        "note": database.get_note(note_id),
    }


@router.post("/{note_id}/clear-manual-edit")
def clear_manual_edit(note_id: int):
    """清除人工编辑标记，让笔记可以重新被 OCR 覆盖。"""
    note = database.get_note(note_id)
    if not note:
        raise HTTPException(status_code=404, detail="笔记不存在")
    database.update_note_fields(note_id, manually_edited=False)
    return {"note_id": note_id, "manually_edited": False}


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

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
    - 若 ocr_text 被修改，自动提取差异行存为 ocr_correction 记忆
      （下次 OCR 同类笔记时，LLM 会拿到这些"用户习惯修正"作为提示）
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

    # 提取 OCR 修正差异并存为记忆（反馈学习）
    correction_info = {"extracted": 0, "memories_created": 0}
    if body.ocr_text is not None:
        old_ocr = note.get("ocr_text") or ""
        new_ocr = body.ocr_text
        corrections = _extract_ocr_corrections(old_ocr, new_ocr)
        correction_info["extracted"] = len(corrections)
        # 复用一个 OpenAI client 生成 embedding（避免每条都重新创建）
        mem_client = ocr_processor._get_client()
        for old_line, new_line in corrections:
            try:
                embedding = None
                content = f'"{old_line}" → "{new_line}"'
                if mem_client is not None:
                    try:
                        embedding = ocr_processor._embed_text(mem_client, content)
                    except Exception:
                        pass
                database.insert_memory(
                    type="ocr_correction",
                    content=content,
                    source="manual_edit",
                    weight=0.7,
                    embedding=embedding,
                )
                correction_info["memories_created"] += 1
            except Exception:
                pass  # 记忆存储失败不影响编辑

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
        "corrections": correction_info,
        "note": database.get_note(note_id),
    }


def _extract_ocr_corrections(old_text: str, new_text: str) -> List[tuple]:
    """对比新旧 OCR 文本，提取被修改的行（difflib）。

    返回 [(old_line, new_line), ...] 列表，仅保留实际有意义的修改
    （剔除空白差异、过短差异、纯顺序调整等）。
    """
    import difflib
    old_lines = old_text.splitlines()
    new_lines = new_text.splitlines()

    corrections: List[tuple] = []
    # 用 SequenceMatcher 按行对比
    matcher = difflib.SequenceMatcher(a=old_lines, b=new_lines, autojunk=False)
    for tag, i1, i2, j1, j2 in matcher.get_opcodes():
        if tag == "replace":
            # 替换：old[i1:i2] 被替换为 new[j1:j2]
            old_chunk = "\n".join(old_lines[i1:i2]).strip()
            new_chunk = "\n".join(new_lines[j1:j2]).strip()
            # 只保留有意义的修改：长度 2-100 字符，且不是纯空白差异
            if (2 <= len(old_chunk) <= 100
                    and 2 <= len(new_chunk) <= 100
                    and old_chunk != new_chunk):
                # 相似度阈值：避免完全无关的修改
                ratio = difflib.SequenceMatcher(None, old_chunk, new_chunk).ratio()
                if 0.3 <= ratio <= 0.95:
                    corrections.append((old_chunk, new_chunk))
        elif tag == "delete":
            # 删除行：不存为修正（删除的内容不需要学习）
            pass
        elif tag == "insert":
            # 新增行：不存为修正（纯新增内容不是 OCR 错误）
            pass

    # 去重（同一条修正可能被多次提取）
    seen = set()
    unique = []
    for old_c, new_c in corrections:
        key = (old_c, new_c)
        if key not in seen:
            seen.add(key)
            unique.append((old_c, new_c))
    # 限制最多 5 条，避免一次编辑产生过多记忆
    return unique[:5]


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

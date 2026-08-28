"""笔记相关 API 路由。"""
from __future__ import annotations

import os
from typing import Any, List, Optional

import bundle_builder
from fastapi import APIRouter, HTTPException, Query
from fastapi.responses import FileResponse
from pydantic import BaseModel

import database
import ocr_processor
import scheduler
import settings_store

router = APIRouter(prefix="/api/notes", tags=["notes"])


@router.get("/{note_id}/bundle")
def get_note_bundle(note_id: int):
    """Rebuild and download a note's persistent Markdown/image ZIP bundle."""
    note = database.get_note(note_id)
    if not note:
        raise HTTPException(status_code=404, detail="笔记不存在")

    source_path = os.path.realpath(str(note.get("file_path") or ""))
    ext = os.path.splitext(source_path)[1].lower()
    if ext not in (".md", ".markdown"):
        raise HTTPException(status_code=400, detail="只有 Markdown 笔记支持整合包导出")
    if not os.path.isfile(source_path):
        raise HTTPException(status_code=404, detail="原始 Markdown 文件不存在")

    try:
        info = bundle_builder.build_markdown_bundle(note_id)
    except Exception as e:
        try:
            source_path_exists = os.path.isfile(source_path)
        except OSError:
            source_path_exists = False
        detail = "原始 Markdown 文件不存在" if not source_path_exists else f"生成整合包失败：{e}"
        raise HTTPException(status_code=404 if not source_path_exists else 500, detail=detail)

    archive_path = info["archive"]
    return FileResponse(
        archive_path,
        media_type="application/zip",
        filename=os.path.basename(archive_path),
    )


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
        ".txt": "text/plain; charset=utf-8",
        ".md": "text/markdown; charset=utf-8",
        ".markdown": "text/markdown; charset=utf-8",
        ".docx": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
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
    mermaid: Optional[str] = None
    knowledge_kind: Optional[str] = None
    practice_status: Optional[str] = None
    condition_text: Optional[str] = None
    action_text: Optional[str] = None
    consequence_text: Optional[str] = None
    evidence_text: Optional[str] = None
    next_action_text: Optional[str] = None
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
    if body.mermaid is not None:
        updates["mermaid"] = body.mermaid.strip()

    if body.knowledge_kind is not None:
        if body.knowledge_kind not in ("practice", "reference", "noise", "unclassified"):
            raise HTTPException(400, "knowledge_kind 必须是 practice/reference/noise/unclassified")
        updates["knowledge_kind"] = body.knowledge_kind
    if body.practice_status is not None:
        if body.practice_status not in ("done", "attempted", "planned", "external", "unknown"):
            raise HTTPException(400, "practice_status 值无效")
        updates["practice_status"] = body.practice_status
    for field in ("condition_text", "action_text", "consequence_text", "evidence_text", "next_action_text"):
        value = getattr(body, field)
        if value is not None:
            updates[field] = value.strip()
    updates["manually_edited"] = True

    if not any(k != "manually_edited" for k in updates):
        raise HTTPException(status_code=400, detail="未提供任何要更新的字段")

    # 提取 OCR 修正/补充差异并存为记忆（反馈学习）
    correction_info = {"extracted": 0, "memories_created": 0,
                       "corrections": 0, "additions": 0}
    if body.ocr_text is not None:
        old_ocr = note.get("ocr_text") or ""
        new_ocr = body.ocr_text
        corrections = _extract_ocr_corrections(old_ocr, new_ocr)
        correction_info["extracted"] = len(corrections)
        # 复用一个 OpenAI client 生成 embedding（避免每条都重新创建）
        mem_client = ocr_processor._get_client()
        for entry in corrections:
            mem_type, old_line, new_line = entry  # (type, old, new)
            try:
                embedding = None
                if mem_type == "ocr_correction":
                    content = f'"{old_line}" → "{new_line}"'
                    weight = 0.7
                else:  # ocr_addition
                    content = f'用户补充：{new_line}'
                    weight = 0.6  # 补充内容权重略低，因为是用户习惯而非确定修正
                if mem_client is not None:
                    try:
                        embedding = ocr_processor._embed_text(mem_client, content)
                    except Exception:
                        pass
                database.insert_memory(
                    type=mem_type,
                    content=content,
                    source="manual_edit",
                    weight=weight,
                    embedding=embedding,
                )
                correction_info["memories_created"] += 1
                if mem_type == "ocr_correction":
                    correction_info["corrections"] += 1
                else:
                    correction_info["additions"] += 1
            except Exception:
                pass  # 记忆存储失败不影响编辑

    # 写入数据库（先不更新 embedding）
    database.update_note_fields(
        note_id,
        title=updates.get("title"),
        ocr_text=updates.get("ocr_text"),
        summary=updates.get("summary"),
        keywords=updates.get("keywords"),
        mermaid=updates.get("mermaid"),
        manually_edited=True,
    )

    insight_fields = (
        "knowledge_kind", "practice_status", "condition_text",
        "action_text", "consequence_text", "evidence_text", "next_action_text",
    )
    if any(field in updates for field in insight_fields):
        database.update_note_insight(
            note_id,
            knowledge_kind=updates.get("knowledge_kind") or note.get("knowledge_kind") or "unclassified",
            practice_status=updates.get("practice_status") or note.get("practice_status") or "unknown",
            condition_text=updates.get("condition_text", note.get("condition_text")),
            action_text=updates.get("action_text", note.get("action_text")),
            consequence_text=updates.get("consequence_text", note.get("consequence_text")),
            evidence_text=updates.get("evidence_text", note.get("evidence_text")),
            next_action_text=updates.get("next_action_text", note.get("next_action_text")),
            confidence=float(note.get("confidence") or 0.5),
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

    返回 [(type, old_line, new_line), ...] 列表，其中：
      - type='ocr_correction'：替换型修改（错字修正、改写）
      - type='ocr_addition'：新增行（用户补充的批注、思考、扩展内容）

    仅保留实际有意义的修改（剔除空白差异、过短差异、纯顺序调整等）。
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
                    corrections.append(("ocr_correction", old_chunk, new_chunk))
        elif tag == "insert":
            # 新增行：用户主动补充的内容（批注/思考/扩展）
            # 这类内容反映用户的笔记习惯，应该作为 ocr_addition 记忆学习
            new_chunk = "\n".join(new_lines[j1:j2]).strip()
            # 只保留有意义的新增内容：长度 2-200 字符
            if 2 <= len(new_chunk) <= 200:
                # 剔除纯标点/纯数字等无意义新增
                if any(c.isalpha() for c in new_chunk):
                    corrections.append(("ocr_addition", "", new_chunk))
        elif tag == "delete":
            # 删除行：不存为记忆（删除的内容不需要学习）
            pass

    # 去重（同一条修正可能被多次提取）
    seen = set()
    unique = []
    for entry in corrections:
        key = (entry[0], entry[1], entry[2])
        if key not in seen:
            seen.add(key)
            unique.append(entry)
    # 限制最多 8 条（修正 5 + 新增 3），避免一次编辑产生过多记忆
    return unique[:8]


@router.post("/{note_id}/clear-manual-edit")
def clear_manual_edit(note_id: int):
    """清除人工编辑标记，让笔记可以重新被 OCR 覆盖。"""
    note = database.get_note(note_id)
    if not note:
        raise HTTPException(status_code=404, detail="笔记不存在")
    database.update_note_fields(note_id, manually_edited=False)
    return {"note_id": note_id, "manually_edited": False}


@router.delete("/{note_id}")
def delete_note(note_id: int, hard: bool = False):
    """删除笔记（数据库记录 + links + 缩略图）。

    Args:
        hard: 是否同时删除物理文件。默认 False（仅删数据库记录）。
              Syncthing 同步的文件建议让 Syncthing 自己删，这里只清 DB。
    """
    note = database.get_note(note_id)
    if not note:
        raise HTTPException(status_code=404, detail="笔记不存在")
    file_path = note.get("file_path", "")
    ok = database.delete_note(note_id)
    if not ok:
        raise HTTPException(status_code=500, detail="删除失败")
    # 可选：删除物理文件
    if hard and file_path:
        try:
            import os
            if os.path.exists(file_path):
                os.remove(file_path)
        except Exception as e:
            # 物理文件删除失败不回滚 DB（DB 已删，文件残留可接受）
            pass
    return {"deleted": True, "note_id": note_id, "hard": hard}


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

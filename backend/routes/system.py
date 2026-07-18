"""系统信息与维护 API。

为未来开发新功能与日常维护提供入口：系统信息、手动触发扫描、重建链接、
重试失败笔记、数据库压缩、笔记设备/来源统计等。
"""
from __future__ import annotations

import os
import platform
import shutil
import sys
from typing import Any, Dict

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

import database
import graph_api
import scheduler
import settings_store
from config import get_config

router = APIRouter(prefix="/api", tags=["system"])


@router.get("/health")
def health() -> Dict[str, Any]:
    """健康检查。"""
    cfg = get_config()
    model_cfg = settings_store.get_model_config()
    return {
        "status": "ok",
        "openai_configured": bool(cfg.OPENAI_API_KEY),
        "llm_model": model_cfg.get("llm_model", cfg.LLM_MODEL),
        "qa_model": model_cfg.get("qa_model", cfg.QA_MODEL),
        "embedding_model": model_cfg.get("embedding_model", cfg.EMBEDDING_MODEL),
    }


@router.get("/stats")
def stats() -> Dict[str, Any]:
    """知识库统计。"""
    return database.get_stats()


@router.get("/system/info")
def system_info() -> Dict[str, Any]:
    """系统信息：平台、Python 版本、目录、磁盘占用、DB 大小等。"""
    cfg = get_config()
    db_size = 0
    try:
        db_size = os.path.getsize(cfg.DB_PATH)
    except Exception:
        pass
    # synced_notes 目录占用
    notes_size = _dir_size(cfg.SYNCED_NOTES_ROOT)
    thumb_size = _dir_size(cfg.THUMBNAIL_DIR)
    # 磁盘可用空间
    disk = shutil.disk_usage(os.path.abspath(cfg.SYNCED_NOTES_ROOT))
    relay = settings_store.get_relay_config()
    return {
        "platform": {
            "system": platform.system(),
            "release": platform.release(),
            "machine": platform.machine(),
            "processor": platform.processor() or "unknown",
            "python": sys.version.split()[0],
        },
        "paths": {
            "synced_notes_root": os.path.abspath(cfg.SYNCED_NOTES_ROOT),
            "thumbnail_dir": os.path.abspath(cfg.THUMBNAIL_DIR),
            "db_path": os.path.abspath(cfg.DB_PATH),
        },
        "storage": {
            "db_bytes": db_size,
            "notes_bytes": notes_size,
            "thumbnail_bytes": thumb_size,
            "disk_total_bytes": disk.total,
            "disk_used_bytes": disk.used,
            "disk_free_bytes": disk.free,
        },
        "relay": relay,
        "watch_folders_count": len([f for f in settings_store.get_watch_folders() if f.get("enabled", True)]),
    }


# ---------------------------------------------------------------------------
# 维护操作
# ---------------------------------------------------------------------------
@router.post("/system/scan")
def trigger_scan() -> Dict[str, Any]:
    """手动触发一次全量扫描（立即执行，不等 03:00）。"""
    new_count = scheduler.full_scan()
    return {"scanned": True, "new_notes": new_count}


class RebuildLinksRequest(BaseModel):
    note_id: int | None = None  # None 表示全库重建


@router.post("/system/rebuild-links")
def rebuild_links(body: RebuildLinksRequest) -> Dict[str, Any]:
    """重建候选链接。可指定单条笔记，或全库重建。"""
    if body.note_id is not None:
        cnt = graph_api.recompute_links_for_note(body.note_id)
        return {"rebuilt": True, "scope": "single", "note_id": body.note_id, "links": cnt}
    # 全库重建
    total = 0
    for n in database.get_done_notes_with_embeddings():
        try:
            total += graph_api.recompute_links_for_note(n["id"])
        except Exception:
            pass
    return {"rebuilt": True, "scope": "all", "links": total}


@router.post("/system/retry-failed")
def retry_failed() -> Dict[str, Any]:
    """把所有 failed 状态的笔记重置为 pending 并重新入队。"""
    with database._db_lock, database.get_conn() as conn:
        rows = conn.execute("SELECT id FROM notes WHERE status='failed'").fetchall()
    count = 0
    for r in rows:
        database.update_note_status(r["id"], "pending")
        scheduler.enqueue_note(r["id"])
        count += 1
    return {"retried": True, "count": count}


@router.post("/system/vacuum")
def vacuum_db() -> Dict[str, Any]:
    """压缩 SQLite 数据库（回收空间）。"""
    before = 0
    cfg = get_config()
    try:
        before = os.path.getsize(cfg.DB_PATH)
    except Exception:
        pass
    with database._db_lock, database.get_conn() as conn:
        conn.isolation_level = None
        conn.execute("VACUUM;")
        conn.isolation_level = ""
    after = 0
    try:
        after = os.path.getsize(cfg.DB_PATH)
    except Exception:
        pass
    return {"vacuumed": True, "before_bytes": before, "after_bytes": after}


@router.post("/system/reprocess-all")
def reprocess_all() -> Dict[str, Any]:
    """把所有 done 笔记重置为 pending 并重新入队（重新 OCR）。

    用于更换模型后批量重跑。
    """
    with database._db_lock, database.get_conn() as conn:
        rows = conn.execute("SELECT id FROM notes WHERE status='done'").fetchall()
    count = 0
    for r in rows:
        database.update_note_status(r["id"], "pending")
        scheduler.enqueue_note(r["id"])
        count += 1
    return {"reprocessed": True, "count": count}


# ---------------------------------------------------------------------------
# 来源统计：供前端了解已入库笔记的设备分布
# ---------------------------------------------------------------------------
@router.get("/system/sources")
def sources() -> Dict[str, Any]:
    """按 source_device / source_app 统计笔记分布。"""
    with database._db_lock, database.get_conn() as conn:
        rows = conn.execute(
            "SELECT source_device, source_app, COUNT(*) as cnt FROM notes GROUP BY source_device, source_app ORDER BY cnt DESC"
        ).fetchall()
    return {
        "sources": [
            {"device": r["source_device"], "app": r["source_app"], "count": r["cnt"]}
            for r in rows
        ]
    }


# ---------------------------------------------------------------------------
# 工具
# ---------------------------------------------------------------------------
def _dir_size(path: str) -> int:
    """递归计算目录占用字节数。"""
    total = 0
    if not path or not os.path.isdir(path):
        return 0
    for root, _dirs, files in os.walk(path):
        for f in files:
            try:
                total += os.path.getsize(os.path.join(root, f))
            except Exception:
                pass
    return total

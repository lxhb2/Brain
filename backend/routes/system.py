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

from fastapi import APIRouter, HTTPException, Query, Request
from fastapi.responses import FileResponse
from pydantic import BaseModel

import database
import graph_api
import growth
import scheduler
import bundle_builder
import settings_store
from config import get_config, get_watch_dirs_runtime

router = APIRouter(prefix="/api", tags=["system"])

_MARKDOWN_IMAGE_TYPES = {
    ".bmp": "image/bmp",
    ".gif": "image/gif",
    ".jpeg": "image/jpeg",
    ".jpg": "image/jpeg",
    ".png": "image/png",
    ".webp": "image/webp",
}


def _is_realpath_inside(candidate: str, root: str) -> bool:
    """Check a fully-resolved path without allowing ../ traversal outside a root."""
    return candidate == root or candidate.startswith(root.rstrip(os.sep) + os.sep)


@router.get("/health")
def health() -> Dict[str, Any]:
    """健康检查：暴露各组件运行状态。

    任一关键组件失败返回 status=degraded（HTTP 仍 200，让健康检查
    不误判，但前端可据此显示降级提示）。
    """
    cfg = get_config()
    model_cfg = settings_store.get_model_config()

    # 各组件状态
    components: Dict[str, str] = {}

    # watcher
    try:
        import watcher
        components["watcher"] = "ok" if watcher._observers else "stopped"
    except Exception:
        components["watcher"] = "unknown"

    # scheduler
    try:
        import scheduler
        components["scheduler"] = "ok" if scheduler._scheduler else "stopped"
    except Exception:
        components["scheduler"] = "unknown"

    # worker
    try:
        import scheduler
        alive = any(t.is_alive() for t in scheduler._worker_threads) if scheduler._worker_threads else False
        components["worker"] = "ok" if alive else "stopped"
    except Exception:
        components["worker"] = "unknown"

    # DB
    try:
        database.get_stats()
        components["db"] = "ok"
    except Exception:
        components["db"] = "error"

    # LLM key 是否配置
    components["llm"] = "ok" if cfg.OPENAI_API_KEY else "unconfigured"

    degraded = any(v in ("error", "stopped") for v in components.values())
    return {
        "status": "degraded" if degraded else "ok",
        "components": components,
        "openai_configured": bool(cfg.OPENAI_API_KEY),
        "baidu_ocr_enabled": bool(cfg.BAIDU_OCR_ENABLED and cfg.BAIDU_OCR_API_KEY and cfg.BAIDU_OCR_SECRET_KEY),
        "llm_model": model_cfg.get("llm_model", cfg.LLM_MODEL),
        "qa_model": model_cfg.get("qa_model", cfg.QA_MODEL),
        "embedding_model": model_cfg.get("embedding_model", cfg.EMBEDDING_MODEL),
}


@router.get("/files/markdown-image")
def get_markdown_image(path: str = Query(min_length=1)):
    """Serve an image referenced by an ingested Markdown note."""
    cfg = get_config()
    roots = list(get_watch_dirs_runtime().keys())
    synced_root = os.path.abspath(cfg.SYNCED_NOTES_ROOT)
    roots.append(os.path.dirname(synced_root))

    requested = os.path.realpath(path)
    if os.path.splitext(requested)[1].lower() not in _MARKDOWN_IMAGE_TYPES:
        raise HTTPException(status_code=404, detail="不是支持的图片文件")
    if not any(_is_realpath_inside(requested, os.path.realpath(str(root))) for root in roots):
        raise HTTPException(status_code=404, detail="路径不在监听目录内")
    if not os.path.isfile(requested):
        raise HTTPException(status_code=404, detail="图片不存在")

    media_type = _MARKDOWN_IMAGE_TYPES[os.path.splitext(requested)[1].lower()]
    return FileResponse(requested, media_type=media_type)


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
    cloud_root = os.path.abspath(
        os.path.join(os.path.dirname(os.path.abspath(cfg.SYNCED_NOTES_ROOT)), "cloud")
    )
    cloud_size = _dir_size(cloud_root)
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
            "cloud_root": cloud_root,
        },
        "storage": {
            "db_bytes": db_size,
            "notes_bytes": notes_size,
            "thumbnail_bytes": thumb_size,
            "cloud_bytes": cloud_size,
            "disk_total_bytes": disk.total,
            "disk_used_bytes": disk.used,
            "disk_free_bytes": disk.free,
        },
        "relay": relay,
        "watch_folders_count": len([f for f in settings_store.get_watch_folders() if f.get("enabled", True)]),
    }


@router.get("/system/access")
def access_info(request: Request) -> Dict[str, Any]:
    """访问地址解析：返回当前 Host 对应的 Brain/云盘/Syncthing 地址。"""
    host = (request.headers.get("host") or "").strip()
    hostname = host
    if hostname.startswith("["):
        hostname = hostname[1:].split("]")[0]
    elif ":" in hostname:
        hostname = hostname.rsplit(":", 1)[0]
    if not hostname:
        hostname = "brain.local"

    cfg = get_config()
    cloud_root = os.path.abspath(
        os.path.join(os.path.dirname(os.path.abspath(cfg.SYNCED_NOTES_ROOT)), "cloud")
    )
    return {
        "host": host or None,
        "hostname": hostname,
        "mdns_host": "brain.local",
        "ports": {
            "frontend": 8080,
            "api": 8000,
            "cloud_web": 8090,
            "syncthing": 8384,
        },
        "urls": {
            "brain_web": f"http://{hostname}:8080",
            "cloud_web_client": f"http://{hostname}:8090/web/client",
            "api_health": f"http://{hostname}:8000/api/health",
            "syncthing_web": f"http://{hostname}:8384",
        },
        "cloud": {
            "root": cloud_root,
            "upload_subdir": "from-brain",
        },
    }


# ---------------------------------------------------------------------------
# 维护操作
# ---------------------------------------------------------------------------
@router.post("/system/scan")
def trigger_scan() -> Dict[str, Any]:
    """手动触发一次全量扫描（立即执行，不等 03:00）。"""
    new_count = scheduler.full_scan()
    return {"scanned": True, "new_notes": new_count}


class IgnoredFileRequest(BaseModel):
    file_path: str = Query(min_length=1)
    file_hash: str | None = None
    reason: str = "manual"


@router.get("/system/ignored-files")
def list_ignored_files(limit: int = 100) -> Dict[str, Any]:
    """List files excluded from future scanner ingestion."""
    return {"items": database.list_ignored_files(limit=max(1, min(int(limit), 500)))}


@router.post("/system/ignored-files")
def add_ignored_file(body: IgnoredFileRequest) -> Dict[str, Any]:
    """Exclude a historical or duplicate source file from automatic ingestion."""
    item = database.add_ignored_file(
        file_path=body.file_path,
        file_hash=body.file_hash,
        reason=body.reason,
    )
    database.insert_activity(
        event_type="upload",
        message=f"扫描忽略规则已添加：{item['file_path']}",
    )
    return {"added": True, "item": item}


@router.post("/system/backfill-markdown-bundles")
def backfill_markdown_bundles(limit: int = 100) -> Dict[str, Any]:
    """Build persistent bundles for Markdown notes processed before this feature."""
    safe_limit = max(1, min(int(limit), 500))
    with database._db_lock, database.get_conn() as conn:
        rows = conn.execute(
            """
            SELECT id, title FROM notes
            WHERE status = 'done'
              AND (LOWER(file_path) LIKE '%.md' OR LOWER(file_path) LIKE '%.markdown')
            ORDER BY id DESC LIMIT ?
            """,
            (safe_limit,),
        ).fetchall()

    results: list[Dict[str, Any]] = []
    succeeded = 0
    for row in rows:
        try:
            info = bundle_builder.build_markdown_bundle(int(row["id"]))
            results.append({"note_id": int(row["id"]), "archive": info["archive"], "ok": True})
            succeeded += 1
        except Exception as exc:
            results.append({"note_id": int(row["id"]), "error": str(exc), "ok": False})
    return {"rebuilt": True, "total": len(results), "succeeded": succeeded, "results": results}


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
    """把所有 failed 状态的笔记重置为 pending 并重新入队。

    注意：retry_count 会被保留（避免无限重试），如果想清零请用
    /system/reset-retry-count。
    """
    count = scheduler.retry_failed_ocr()
    return {"retried": True, "count": count}


@router.post("/system/daily-summary")
def trigger_daily_summary(date: str | None = None) -> Dict[str, Any]:
    """手动触发生成每日归纳。

    Args:
        date: YYYY-MM-DD 格式。None 表示今天。
    """
    result = scheduler.generate_daily_summary(target_date=date)
    if not result:
        return {"generated": False, "reason": "无 done 笔记或 LLM 失败"}
    return {"generated": True, **result}


@router.post("/system/growth-review")
def trigger_growth_review(date: str | None = None) -> Dict[str, Any]:
    """手动触发成长审核。date 使用 YYYY-MM-DD，默认今天。"""
    result = growth.generate_daily_review(target_date=date)
    if not result:
        return {"generated": False, "reason": "没有可审核的笔记/卡片，或本地模型返回失败"}
    return {"generated": True, **result}


@router.post("/system/growth-triage")
def trigger_growth_triage(limit: int = 3) -> Dict[str, Any]:
    """手动分诊少量未分类笔记。"""
    return growth.triage_pending_notes(limit=max(1, min(limit, 10)))


@router.get("/system/daily-summaries")
def list_daily_summaries(limit: int = 7) -> Dict[str, Any]:
    """列出最近 N 天的归纳。"""
    return {"summaries": database.list_recent_daily_summaries(limit=limit)}


@router.get("/system/growth-reviews")
def list_growth_reviews(limit: int = 7) -> Dict[str, Any]:
    """列出最近 N 天成长审核索引。"""
    return {"reviews": database.list_growth_reviews(limit=limit)}


@router.get("/system/growth-reviews/{review_date}")
def get_growth_review(review_date: str) -> Dict[str, Any]:
    """获取某天成长审核正文。"""
    review = database.get_growth_review(review_date)
    if not review:
        raise HTTPException(status_code=404, detail="该日期无成长审核")
    return review


@router.get("/system/daily-summaries/{date}")
def get_daily_summary_by_date(date: str) -> Dict[str, Any]:
    """获取某天的归纳。"""
    summary = database.get_daily_summary(date)
    if not summary:
        raise HTTPException(status_code=404, detail="该日期无归纳")
    return summary


@router.post("/system/decay")
def trigger_decay() -> Dict[str, Any]:
    """手动触发一次记忆/链接衰减。"""
    link_result = database.decay_link_weights()
    mem_result = database.decay_memory_weights()
    return {"links": link_result, "memories": mem_result}


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
# 轻量活动日志与备份
# ---------------------------------------------------------------------------
@router.get("/activity-logs")
def activity_logs(
    event_type: str | None = None,
    limit: int = 100,
    offset: int = 0,
) -> Dict[str, Any]:
    """列出最近的模型任务、上传、备份和错误记录。"""
    return database.list_activity_logs(
        event_type=event_type,
        limit=limit,
        offset=offset,
    )


@router.post("/system/backup")
def create_backup() -> Dict[str, Any]:
    """手动创建一次 SQLite 在线备份。"""
    return database.create_database_backup()


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

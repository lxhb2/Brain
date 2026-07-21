"""笔记上传接口。

允许手机/平板通过 HTTP 直接上传手写笔记图片（拍照或选文件），
无需 Syncthing。上传后主动入库并入队 OCR 处理（不依赖 watcher，
因为上传目录是动态生成的 <device>-<app>/<yyyymmdd>/，可能不在
watcher 监听列表里）。
"""
from __future__ import annotations

import logging
import os
import time
from datetime import datetime
from typing import Dict, List, Optional

from fastapi import APIRouter, File, Form, UploadFile
from fastapi.responses import JSONResponse

import database
import ocr_processor
import scheduler
from config import get_config

logger = logging.getLogger("brain.routes.upload")

router = APIRouter(prefix="/api", tags=["upload"])

# 允许的文件扩展名（与 watcher 保持一致）
ALLOWED_EXTS = {".pdf", ".png", ".jpg", ".jpeg", ".txt", ".md", ".markdown", ".docx"}
# 单文件大小上限：50MB（手写笔记图片足够）
MAX_FILE_SIZE = 50 * 1024 * 1024
# 默认上传目录（相对 SYNCED_NOTES_ROOT）
DEFAULT_SUBDIR = "uploads"


def _ensure_upload_dir(device: str = "", app: str = "") -> str:
    """确保上传目录存在，返回绝对路径。

    目录结构：SYNCED_NOTES_ROOT/<device>-<app or uploads>/<yyyymmdd>/
    """
    cfg = get_config()
    subdir = f"{device}-{app}" if device and app else DEFAULT_SUBDIR
    today = datetime.now().strftime("%Y%m%d")
    upload_dir = os.path.abspath(os.path.join(cfg.SYNCED_NOTES_ROOT, subdir, today))
    os.makedirs(upload_dir, exist_ok=True)
    return upload_dir


def _safe_filename(name: str) -> str:
    """生成安全的文件名，避免特殊字符和中文乱码。"""
    if not name:
        return f"upload_{int(time.time())}.txt"
    # 取扩展名
    _, ext = os.path.splitext(name)
    if ext.lower() not in ALLOWED_EXTS:
        ext = ".txt"
    # 用时间戳 + 随机数生成唯一文件名
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    return f"upload_{ts}_{int(time.time()*1000) % 10000}{ext.lower()}"


@router.post("/upload")
async def upload_note(
    files: List[UploadFile] = File(...),
    device: Optional[str] = Form(None),
    app: Optional[str] = Form(None),
):
    """上传一个或多个手写笔记图片。

    - files: 文件列表（multipart/form-data）
    - device: 设备名（可选，如 'android'、'iphone'）
    - app: 来源应用（可选，如 'camera'、'gallery'）

    返回上传结果，文件会被 watcher 自动检测并 OCR。
    """
    if not files:
        return JSONResponse(
            status_code=400,
            content={"error": "未提供文件"},
        )

    # 识别设备信息（用于文件夹归类）
    device = (device or "mobile").lower().strip()
    app = (app or "camera").lower().strip()

    upload_dir = _ensure_upload_dir(device, app)
    saved_files: List[Dict] = []

    for idx, f in enumerate(files):
        # 校验扩展名
        original_name = f.filename or f"file_{idx}"
        _, ext = os.path.splitext(original_name)
        if ext.lower() not in ALLOWED_EXTS:
            saved_files.append({
                "filename": original_name,
                "success": False,
                "error": f"不支持的文件类型: {ext}",
            })
            continue

        # 读取内容并校验大小
        content = await f.read()
        if len(content) > MAX_FILE_SIZE:
            saved_files.append({
                "filename": original_name,
                "success": False,
                "error": f"文件过大: {len(content) / 1024 / 1024:.1f}MB（上限 {MAX_FILE_SIZE / 1024 / 1024:.0f}MB）",
            })
            continue

        # 保存
        safe_name = _safe_filename(original_name)
        save_path = os.path.join(upload_dir, safe_name)
        try:
            with open(save_path, "wb") as fp:
                fp.write(content)
            # 主动入库 + 入队，不依赖 watcher
            enqueue_status = "queued"
            enqueue_err = ""
            note_id = None
            try:
                file_hash = ocr_processor.compute_file_hash(save_path)
                # 去重：已存在则复用，否则插入新记录
                existing = database.get_note_by_path(save_path)
                if existing:
                    note_id = existing["id"]
                    if existing.get("status") not in ("done", "processing"):
                        scheduler.enqueue_note(note_id)
                else:
                    note_id = database.insert_note(
                        file_path=save_path,
                        file_hash=file_hash,
                        source_device=device,
                        source_app=app,
                        status="pending",
                    )
                    if note_id:
                        scheduler.enqueue_note(note_id)
            except Exception as e:
                enqueue_status = "saved_but_not_queued"
                enqueue_err = str(e)
                logger.exception("上传后入队失败: %s", save_path)

            saved_files.append({
                "filename": original_name,
                "saved_as": safe_name,
                "path": save_path,
                "size_bytes": len(content),
                "success": True,
                "note_id": note_id,
                "enqueue": enqueue_status,
                "enqueue_error": enqueue_err or None,
            })
            logger.info("上传成功: %s -> %s (%.1fKB, note_id=%s, %s)",
                        original_name, save_path, len(content) / 1024,
                        note_id, enqueue_status)
        except Exception as e:
            saved_files.append({
                "filename": original_name,
                "success": False,
                "error": str(e),
            })
            logger.exception("上传失败: %s", original_name)

    success_count = sum(1 for f in saved_files if f.get("success"))
    return {
        "status": "ok",
        "device": device,
        "app": app,
        "total": len(files),
        "success": success_count,
        "failed": len(files) - success_count,
        "files": saved_files,
        "message": f"上传完成：{success_count}/{len(files)} 个文件成功，已入队 OCR 处理",
    }

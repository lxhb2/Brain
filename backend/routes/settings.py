"""设置与文件夹管理 API。

提供运行时可配置项的读写，以及监听文件夹的手动添加 / 自动扫描发现。

分组：
  GET    /api/settings              读取全部设置
  PUT    /api/settings              批量更新设置
  GET    /api/folders               列出监听文件夹
  POST   /api/folders               手动添加监听文件夹
  DELETE /api/folders/{id}          删除监听文件夹
  PATCH  /api/folders/{id}          启停/编辑文件夹
  POST   /api/folders/scan          自动扫描某根目录，发现候选笔记文件夹
  POST   /api/folders/test          测试路径是否可访问
"""
from __future__ import annotations

import os
import uuid
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

import settings_store
import watcher
from config import get_config, normalize_abs_watch_path
from ocr_processor import clear_client_cache

router = APIRouter(prefix="/api", tags=["settings"])

SUPPORTED_EXTS = (".pdf", ".png", ".jpg", ".jpeg", ".txt", ".md", ".markdown", ".docx")


# ---------------------------------------------------------------------------
# 设置整体读写
# ---------------------------------------------------------------------------
@router.get("/settings")
def get_settings() -> Dict[str, Any]:
    """读取全部设置。"""
    return settings_store.get_all_settings()


class SettingsUpdate(BaseModel):
    watch_folders: Optional[List[Dict[str, Any]]] = None
    model: Optional[Dict[str, Any]] = None
    ocr_models: Optional[List[Dict[str, Any]]] = None
    relay: Optional[Dict[str, Any]] = None
    link_params: Optional[Dict[str, Any]] = None
    ui: Optional[Dict[str, Any]] = None


@router.put("/settings")
def update_settings(body: SettingsUpdate) -> Dict[str, Any]:
    """批量更新设置（仅更新提供的字段）。"""
    if body.model is not None:
        settings_store.set_model_config(body.model)
    if body.ocr_models is not None:
        settings_store.set_ocr_models(body.ocr_models)
    if body.relay is not None:
        settings_store.set_relay_config(body.relay)
    if body.link_params is not None:
        settings_store.set_link_params(body.link_params)
    if body.ui is not None:
        settings_store.set_ui_prefs(body.ui)
    if body.watch_folders is not None:
        settings_store.set_watch_folders(body.watch_folders)
        # 文件夹变更后重载 watcher
        try:
            watcher.reconfigure_watcher()
        except Exception:
            pass
    # 三类 API 都可能换 endpoint/key；清空缓存让下一次调用立即使用新配置。
    clear_client_cache()
    return settings_store.get_all_settings()


# ---------------------------------------------------------------------------
# OCR 模型管理（独立接口，便于前端单独操作）
# ---------------------------------------------------------------------------
class OcrModelItem(BaseModel):
    id: Optional[str] = None
    name: str
    model: str
    enabled: bool = True
    is_primary: bool = False


@router.get("/ocr-models")
def list_ocr_models() -> Dict[str, Any]:
    """列出所有 OCR 模型配置。"""
    return {"models": settings_store.get_ocr_models()}


@router.post("/ocr-models/reset")
def reset_ocr_models() -> Dict[str, Any]:
    """重置 OCR 模型列表为默认配置（用 OCR API 模型作为 primary）。

    用于修复历史误配置或切换默认模型后让设置页生效。
    """
    settings_store.reset_ocr_models()
    return {"models": settings_store.get_ocr_models()}


@router.post("/ocr-models/baidu/test")
def test_baidu_ocr() -> Dict[str, Any]:
    """测试百度 OCR 连通性。

    用一张内置的测试图片调一次百度 handwriting 接口，
    返回识别字符数和前 50 字符。
    """
    cfg = get_config()
    if not (cfg.BAIDU_OCR_API_KEY and cfg.BAIDU_OCR_SECRET_KEY):
        return {"ok": False, "error": "百度 OCR 未配置 API_KEY / SECRET_KEY"}
    try:
        import baidu_ocr
        import io
        from PIL import Image, ImageDraw

        # 生成一张测试图片（白底黑字「测试百度 OCR」）
        img = Image.new("RGB", (400, 100), "white")
        draw = ImageDraw.Draw(img)
        draw.text((30, 30), "Hello 百度 OCR 测试", fill="black")
        buf = io.BytesIO()
        img.save(buf, format="PNG")
        text = baidu_ocr.recognize_image(
            buf.getvalue(),
            api_key=cfg.BAIDU_OCR_API_KEY,
            secret_key=cfg.BAIDU_OCR_SECRET_KEY,
        )
        return {
            "ok": True,
            "chars": len(text),
            "preview": text[:50],
            "message": f"识别到 {len(text)} 字符",
        }
    except Exception as e:
        return {"ok": False, "error": str(e)}


@router.post("/ocr-models")
def add_ocr_model(body: OcrModelItem) -> Dict[str, Any]:
    """新增一个 OCR 模型。"""
    models = settings_store.get_ocr_models()
    new_item = {
        "id": body.id or uuid.uuid4().hex[:10],
        "name": body.name,
        "model": body.model,
        "enabled": body.enabled,
        "is_primary": body.is_primary,
    }
    models.append(new_item)
    settings_store.set_ocr_models(models)
    return {"model": new_item, "models": settings_store.get_ocr_models()}


@router.patch("/ocr-models/{model_id}")
def patch_ocr_model(model_id: str, body: OcrModelItem) -> Dict[str, Any]:
    """编辑一个 OCR 模型（name/model/enabled/is_primary）。"""
    models = settings_store.get_ocr_models()
    found = False
    for m in models:
        if m["id"] == model_id:
            if body.name is not None:
                m["name"] = body.name
            if body.model is not None:
                m["model"] = body.model
            if body.enabled is not None:
                m["enabled"] = body.enabled
            if body.is_primary is not None:
                m["is_primary"] = body.is_primary
            found = True
            break
    if not found:
        raise HTTPException(status_code=404, detail="OCR 模型不存在")
    settings_store.set_ocr_models(models)
    return {"model": next(m for m in settings_store.get_ocr_models() if m["id"] == model_id),
            "models": settings_store.get_ocr_models()}


@router.delete("/ocr-models/{model_id}")
def delete_ocr_model(model_id: str) -> Dict[str, Any]:
    """删除一个 OCR 模型（保证至少保留一个 primary）。"""
    models = settings_store.get_ocr_models()
    new_models = [m for m in models if m["id"] != model_id]
    if len(new_models) == len(models):
        raise HTTPException(status_code=404, detail="OCR 模型不存在")
    if not new_models:
        raise HTTPException(status_code=400, detail="至少保留一个 OCR 模型")
    settings_store.set_ocr_models(new_models)
    return {"deleted": True, "models": settings_store.get_ocr_models()}


# ---------------------------------------------------------------------------
# 监听文件夹：手动添加
# ---------------------------------------------------------------------------
class FolderCreate(BaseModel):
    path: str = Field(..., description="文件夹绝对路径或相对路径")
    device: str = Field("自定义设备", description="设备标签")
    app: str = Field("自定义应用", description="应用标签")
    recursive: bool = Field(True, description="是否递归监听子目录")


@router.get("/folders")
def list_folders() -> Dict[str, Any]:
    """列出全部监听文件夹配置。"""
    return {"folders": settings_store.get_watch_folders()}


@router.post("/folders")
def add_folder(body: FolderCreate) -> Dict[str, Any]:
    """手动添加一个监听文件夹，并立即生效（重载 watcher）。"""
    abs_path = normalize_abs_watch_path(body.path)
    if not os.path.isdir(abs_path):
        # 尝试创建
        try:
            os.makedirs(abs_path, exist_ok=True)
        except Exception as e:
            raise HTTPException(status_code=400, detail=f"路径不存在且无法创建: {e}")
    folder = settings_store.add_watch_folder(
        path=abs_path, device=body.device, app=body.app, recursive=body.recursive, auto=False
    )
    try:
        watcher.reconfigure_watcher()
    except Exception:
        pass
    return {"folder": folder, "watcher_reloaded": True}


class FolderPatch(BaseModel):
    enabled: Optional[bool] = None
    device: Optional[str] = None
    app: Optional[str] = None
    recursive: Optional[bool] = None


@router.patch("/folders/{folder_id}")
def patch_folder(folder_id: str, body: FolderPatch) -> Dict[str, Any]:
    """编辑/启停某个监听文件夹。"""
    folders = settings_store.get_watch_folders()
    found = False
    for f in folders:
        if f["id"] == folder_id:
            if body.enabled is not None:
                f["enabled"] = body.enabled
            if body.device is not None:
                f["device"] = body.device
            if body.app is not None:
                f["app"] = body.app
            if body.recursive is not None:
                f["recursive"] = body.recursive
            found = True
            break
    if not found:
        raise HTTPException(status_code=404, detail="文件夹不存在")
    settings_store.set_watch_folders(folders)
    try:
        watcher.reconfigure_watcher()
    except Exception:
        pass
    return {"folder": next(f for f in folders if f["id"] == folder_id), "watcher_reloaded": True}


@router.delete("/folders/{folder_id}")
def delete_folder(folder_id: str) -> Dict[str, Any]:
    """删除某个监听文件夹配置（不删磁盘文件）。"""
    ok = settings_store.remove_watch_folder(folder_id)
    if not ok:
        raise HTTPException(status_code=404, detail="文件夹不存在")
    try:
        watcher.reconfigure_watcher()
    except Exception:
        pass
    return {"deleted": True, "watcher_reloaded": True}


# ---------------------------------------------------------------------------
# 自动扫描：发现候选笔记文件夹
# ---------------------------------------------------------------------------
class ScanRequest(BaseModel):
    root: str = Field(..., description="要扫描的根目录路径")
    max_depth: int = Field(3, description="最大递归深度", ge=1, le=6)


@router.post("/folders/scan")
def scan_folders(body: ScanRequest) -> Dict[str, Any]:
    """自动扫描某根目录，返回包含笔记文件的候选子文件夹。

    用于「自动扫描」模式：用户指定一个根目录（如 Syncthing 同步根），
    系统遍历子目录，发现含 .pdf/.png/.jpg 的文件夹并给出建议 device/app。
    """
    root = normalize_abs_watch_path(body.root)
    if not os.path.isdir(root):
        raise HTTPException(status_code=400, detail=f"根目录不存在: {root}")

    discovered: List[Dict[str, Any]] = []
    for dirpath, dirnames, filenames in os.walk(root):
        # 控制深度
        rel = os.path.relpath(dirpath, root)
        depth = 0 if rel == "." else rel.count(os.sep) + 1
        if depth > body.max_depth:
            dirnames[:] = []  # 不再深入
            continue
        # 跳过隐藏目录
        dirnames[:] = [d for d in dirnames if not d.startswith(".") and d != "__pycache__"]

        note_files = [f for f in filenames if os.path.splitext(f)[1].lower() in SUPPORTED_EXTS and not f.startswith(".")]
        if not note_files:
            continue

        # 推断 device/app
        device, app = _guess_device_app(dirpath)
        discovered.append(
            {
                "path": dirpath,
                "name": os.path.basename(dirpath) or root,
                "file_count": len(note_files),
                "sample_files": note_files[:3],
                "suggested_device": device,
                "suggested_app": app,
            }
        )

    return {"root": root, "discovered": discovered, "total": len(discovered)}


def _guess_device_app(path: str) -> tuple[str, str]:
    """根据路径名启发式推断设备/应用标签。"""
    low = path.lower()
    if "ipad" in low or "goodnotes" in low or "notability" in low:
        return "iPad", "GoodNotes" if "goodnotes" in low else "Notability"
    if "android" in low or "samsung" in low:
        return "Android", "Samsung Notes"
    if "onenote" in low or "pc" in low or "windows" in low or "desktop" in low:
        return "PC", "OneNote"
    if "camera" in low or "photo" in low or "whiteboard" in low or "白板" in low:
        return "Camera", "拍摄"
    if "mac" in low or "bear" in low or "备忘" in low:
        return "Mac", "Bear"
    return "未知设备", "未知应用"


# ---------------------------------------------------------------------------
# 路径测试
# ---------------------------------------------------------------------------
class PathTest(BaseModel):
    path: str


@router.post("/folders/test")
def test_path(body: PathTest) -> Dict[str, Any]:
    """测试路径是否可访问，返回存在性、可读性、文件数等信息。"""
    abs_path = normalize_abs_watch_path(body.path)
    exists = os.path.exists(abs_path)
    is_dir = os.path.isdir(abs_path)
    readable = os.access(abs_path, os.R_OK) if exists else False
    file_count = 0
    note_count = 0
    if is_dir and readable:
        try:
            for _, _, files in os.walk(abs_path):
                for f in files:
                    file_count += 1
                    if os.path.splitext(f)[1].lower() in SUPPORTED_EXTS:
                        note_count += 1
        except Exception:
            pass
    return {
        "path": abs_path,
        "exists": exists,
        "is_dir": is_dir,
        "readable": readable,
        "file_count": file_count,
        "note_count": note_count,
    }

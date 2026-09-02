"""运行时设置存储层。

把可在前端配置的项持久化到 SQLite settings 表（key-value，value 为 JSON）。
设计目标：未来开发新功能与维护时，所有可调参数都通过这里统一读写，
env 变量仅作为「首次启动的默认种子」。

设置的 key 划分：
  - watch_folders: 监听文件夹列表 [{id, path, device, app, enabled, recursive}]
  - model:         OCR / LLM / Embedding 三组 API 配置；明文 key 只写库、不回显
  - ocr_models:    OCR 模型列表 [{id, name, model, enabled, is_primary}]
                    多模型 fallback 共用 OCR API 配置
  - relay:         中继器位置 {location: local|cloud, host, port, note}
  - link_params:   链接权重 {alpha, beta, gamma, threshold}
  - ui:            前端偏好 {theme, device_override}
"""
from __future__ import annotations

import json
import os
import threading
import uuid
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

import database
from config import get_config, normalize_abs_watch_path, normalize_watch_path

# 内存缓存，避免每次读设置都查库
_cache: Dict[str, Any] = {}
_cache_lock = threading.Lock()
_loaded = False
_API_KINDS = ("ocr", "llm", "embedding")


# ---------------------------------------------------------------------------
# 底层读写
# ---------------------------------------------------------------------------
def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _get_raw(key: str) -> Optional[Any]:
    """从 DB 读取一个设置项（带内存缓存）。"""
    global _loaded
    with _cache_lock:
        if not _loaded:
            _load_all_locked()
        if key in _cache:
            return _cache[key]
    # 缓存未命中再查库
    with database._db_lock, database.get_conn() as conn:
        row = conn.execute("SELECT value FROM settings WHERE key=?", (key,)).fetchone()
    if row is None:
        return None
    try:
        val = json.loads(row["value"])
    except Exception:
        val = row["value"]
    with _cache_lock:
        _cache[key] = val
    return val


def _set_raw(key: str, value: Any) -> None:
    """写入一个设置项并更新缓存。"""
    payload = json.dumps(value, ensure_ascii=False)
    with database._db_lock, database.get_conn() as conn:
        conn.execute(
            "INSERT INTO settings(key, value, updated_at) VALUES(?,?,?) "
            "ON CONFLICT(key) DO UPDATE SET value=excluded.value, updated_at=excluded.updated_at",
            (key, payload, _now()),
        )
    with _cache_lock:
        _cache[key] = value


def _load_all_locked() -> None:
    """把全表加载进缓存（持锁调用）。"""
    global _loaded
    try:
        with database._db_lock, database.get_conn() as conn:
            rows = conn.execute("SELECT key, value FROM settings").fetchall()
        for r in rows:
            try:
                _cache[r["key"]] = json.loads(r["value"])
            except Exception:
                _cache[r["key"]] = r["value"]
    except Exception:
        # DB 尚未初始化时，静默返回空
        pass
    _loaded = True


def reload() -> None:
    """清空缓存并重新加载（设置变更后调用）。"""
    global _loaded
    with _cache_lock:
        _cache.clear()
        _loaded = False


# ---------------------------------------------------------------------------
# 默认种子：从 env / config 派生首次值
# ---------------------------------------------------------------------------
def _seed_watch_folders() -> List[Dict[str, Any]]:
    """根据 config.WATCH_DIRS 生成默认监听文件夹列表。"""
    cfg = get_config()
    folders: List[Dict[str, Any]] = []
    for path, meta in cfg.WATCH_DIRS.items():
        folders.append(
            {
                "id": uuid.uuid4().hex[:12],
                "path": os.path.abspath(path),
                "device": meta.get("device", ""),
                "app": meta.get("app", ""),
                "enabled": True,
                "recursive": True,
                "auto": False,  # 是否由自动扫描发现
            }
        )
    return folders


def _ensure_cloud_watch_folder(folders: List[Dict[str, Any]]) -> bool:
    """Keep the private cloud drive connected to the note watcher.

    SFTPGo writes uploads into <data root>/cloud. Existing installations may
    have settings created before that folder existed, so add it once here.
    Users can disable it in Settings; a disabled record will not be re-added.
    """
    cfg = get_config()
    data_root = os.path.dirname(os.path.abspath(cfg.SYNCED_NOTES_ROOT))
    cloud_path = os.path.abspath(os.path.join(data_root, "cloud"))
    if any(
        os.path.abspath(str(item.get("path", ""))) == cloud_path
        for item in folders
    ):
        return False

    folders.append(
        {
            "id": uuid.uuid4().hex[:12],
            "path": cloud_path,
            "device": "cloud",
            "app": "sftpgo",
            "enabled": True,
            "recursive": True,
            "auto": False,
        }
    )
    return True


def _seed_model() -> Dict[str, Any]:
    cfg = get_config()
    return {
        "ocr_model": cfg.OCR_MODEL,
        "ocr_base_url": cfg.OCR_BASE_URL or cfg.OPENAI_BASE_URL or "",
        "llm_model": cfg.LLM_MODEL,
        "llm_base_url": cfg.LLM_BASE_URL or cfg.OPENAI_BASE_URL or "",
        "qa_model": cfg.QA_MODEL,
        "embedding_model": cfg.EMBEDDING_MODEL,
        "embedding_dim": cfg.EMBEDDING_DIM,
        "embedding_base_url": cfg.EMBEDDING_BASE_URL or cfg.OPENAI_BASE_URL or "",
        "openai_base_url": cfg.OPENAI_BASE_URL or "",
        # API Key 仅保存是否已配置的布尔，明文 key 始终只读 env，不落库
        "openai_api_key_set": bool(cfg.OPENAI_API_KEY),
    }


def _seed_relay() -> Dict[str, Any]:
    return {
        # 先做本地 PC 适配，后续上云端时切换为 cloud
        "location": "local",
        "host": "0.0.0.0",
        "port": 8000,
        "note": "本地中继器（PC 端），后续可切换到云端",
    }


def _seed_ocr_models() -> List[Dict[str, Any]]:
    """根据 config.LLM_MODEL 生成默认 OCR 模型列表。

    所有模型共用 OPENAI_BASE_URL 和 OPENAI_API_KEY，
    这里只保存 model id（如 Pro/moonshotai/Kimi-K2.6）。
    用户可在前端设置页添加更多模型（如 Qwen3-VL、豆包 VL）。

    若 config.BAIDU_OCR_ENABLED=True 且配置了 API Key/Secret，
    会额外加入一个 baidu 模型（id="baidu"），由 baidu_ocr 模块处理。
    """
    cfg = get_config()
    models = [
        {
            "id": "default",
            "name": "Kimi K2.6",
            "model": cfg.LLM_MODEL,
            "enabled": True,
            "is_primary": True,
        }
    ]
    if cfg.BAIDU_OCR_ENABLED and cfg.BAIDU_OCR_API_KEY and cfg.BAIDU_OCR_SECRET_KEY:
        models.append(
            {
                "id": "baidu",
                "name": "百度手写 OCR",
                "model": "baidu-handwriting",  # 仅作标识，实际不调 OpenAI 接口
                "enabled": True,
                "is_primary": False,
            }
        )
    return models


def _seed_link_params() -> Dict[str, Any]:
    cfg = get_config()
    return {
        "alpha": cfg.LINK_ALPHA,
        "beta": cfg.LINK_BETA,
        "gamma": cfg.LINK_GAMMA,
        "threshold": cfg.LINK_WEIGHT_THRESHOLD,
    }


# ---------------------------------------------------------------------------
# 对外 API：各设置项的 get/set
# ---------------------------------------------------------------------------
def get_watch_folders() -> List[Dict[str, Any]]:
    val = _get_raw("watch_folders")
    if val is None:
        val = _seed_watch_folders()
    changed = _ensure_cloud_watch_folder(val)
    normalized: List[Dict[str, Any]] = []
    for item in val:
        if not isinstance(item, dict):
            continue
        item = dict(item)
        old_path = str(item.get("path") or "")
        new_path = normalize_watch_path(old_path)
        if new_path != old_path:
            item["path"] = new_path
            changed = True
        normalized.append(item)
    val = normalized
    if changed or _get_raw("watch_folders") is None:
        _set_raw("watch_folders", val)
    return val  # type: ignore[return-value]


def set_watch_folders(folders: List[Dict[str, Any]]) -> None:
    _set_raw("watch_folders", folders)


def _ensure_model_config() -> Dict[str, Any]:
    """读取原始模型配置，并为旧数据补上三组 API 字段。"""
    cfg = get_config()
    val = _get_raw("model")
    if not isinstance(val, dict):
        val = _seed_model()
    defaults = {
        "ocr_model": cfg.OCR_MODEL or cfg.LLM_MODEL,
        "ocr_base_url": cfg.OCR_BASE_URL or cfg.OPENAI_BASE_URL or "",
        "llm_model": cfg.LLM_MODEL,
        "llm_base_url": cfg.LLM_BASE_URL or cfg.OPENAI_BASE_URL or "",
        "qa_model": cfg.QA_MODEL or cfg.LLM_MODEL,
        "embedding_model": cfg.EMBEDDING_MODEL,
        "embedding_dim": cfg.EMBEDDING_DIM,
        "embedding_base_url": cfg.EMBEDDING_BASE_URL or cfg.OPENAI_BASE_URL or "",
        "openai_base_url": cfg.OPENAI_BASE_URL or "",
    }
    changed = False
    for key, default in defaults.items():
        if key not in val:
            val[key] = default
            changed = True
    if changed:
        _set_raw("model", val)
    return val


def _public_model_config(raw: Dict[str, Any]) -> Dict[str, Any]:
    """返回前端可见配置；API key 只返回是否已设置。"""
    cfg = get_config()
    out = dict(raw)
    for kind in _API_KINDS:
        key_field = f"{kind}_api_key"
        out.pop(key_field, None)
        out[f"{key_field}_set"] = bool(
            raw.get(key_field) or getattr(cfg, key_field.upper(), None) or cfg.OPENAI_API_KEY
        )
    out["openai_api_key_set"] = bool(cfg.OPENAI_API_KEY)
    return out


def get_model_config() -> Dict[str, Any]:
    """返回安全化的模型配置，供 API / 前端使用。"""
    return _public_model_config(_ensure_model_config())


def set_model_config(cfg_dict: Dict[str, Any]) -> None:
    """更新模型配置。专用 API key 支持运行时设置，但不会回显明文。"""
    cur = _ensure_model_config()
    for key, value in cfg_dict.items():
        if key == "openai_api_key" or key.endswith("_api_key_set"):
            continue
        if key.endswith("_api_key"):
            key_value = str(value or "").strip()
            # 空值表示“保持不变”，避免只改模型名时误清空密钥。
            if key_value:
                cur[key] = key_value
            continue
        if key == "embedding_dim":
            try:
                cur[key] = int(value)
            except (TypeError, ValueError):
                continue
        else:
            cur[key] = value
    _set_raw("model", cur)


def get_api_config(kind: str) -> Dict[str, Any]:
    """获取一组实际生效的 API 配置。kind 必须是 ocr / llm / embedding。"""
    if kind not in _API_KINDS:
        raise ValueError(f"未知的 API 类型: {kind}")
    raw = _ensure_model_config()
    cfg = get_config()
    upper = kind.upper()
    fallback_model = {
        "ocr": cfg.OCR_MODEL or cfg.LLM_MODEL,
        "llm": cfg.LLM_MODEL,
        "embedding": cfg.EMBEDDING_MODEL,
    }[kind]
    return {
        "model": str(raw.get(f"{kind}_model") or fallback_model),
        "base_url": str(
            raw.get(f"{kind}_base_url")
            or getattr(cfg, f"{upper}_BASE_URL", None)
            or cfg.OPENAI_BASE_URL
            or ""
        ),
        "api_key": str(
            raw.get(f"{kind}_api_key")
            or getattr(cfg, f"{upper}_API_KEY", None)
            or cfg.OPENAI_API_KEY
            or ""
        ),
        "api_key_set": bool(
            raw.get(f"{kind}_api_key")
            or getattr(cfg, f"{upper}_API_KEY", None)
            or cfg.OPENAI_API_KEY
        ),
        "qa_model": str(raw.get("qa_model") or cfg.QA_MODEL or cfg.LLM_MODEL),
        "embedding_dim": int(raw.get("embedding_dim") or cfg.EMBEDDING_DIM),
    }


def get_runtime_model(kind: str) -> str:
    """返回实际调用的模型 ID。"""
    return get_api_config(kind)["model"]


def get_qa_model() -> str:
    """返回问答 / Agent 实际使用的模型 ID。"""
    return get_api_config("llm")["qa_model"]


def get_relay_config() -> Dict[str, Any]:
    val = _get_raw("relay")
    if val is None:
        val = _seed_relay()
        _set_raw("relay", val)
    return val  # type: ignore[return-value]


def set_relay_config(relay: Dict[str, Any]) -> None:
    cur = get_relay_config()
    cur.update(relay)
    _set_raw("relay", cur)


def get_ocr_models() -> List[Dict[str, Any]]:
    """返回 OCR 模型列表。

    保证至少有一个 is_primary=True 的 enabled 模型；
    若用户禁用全部，回退到 default 模型。
    """
    val = _get_raw("ocr_models")
    if val is None:
        val = _seed_ocr_models()
        _set_raw("ocr_models", val)
    return val  # type: ignore[return-value]


def set_ocr_models(models: List[Dict[str, Any]]) -> None:
    """更新 OCR 模型列表。

    保证唯一 is_primary：若多个声明为 primary，只保留第一个；
    若没有 primary，把第一个 enabled 的置为 primary。
    """
    cleaned = []
    primary_set = False
    for m in models:
        if not isinstance(m, dict):
            continue
        mid = m.get("id") or uuid.uuid4().hex[:10]
        name = (m.get("name") or "未命名模型").strip()
        model_id = (m.get("model") or "").strip()
        if not model_id:
            continue  # 没填 model id 的丢弃
        enabled = bool(m.get("enabled", True))
        is_primary = bool(m.get("is_primary", False)) and enabled
        if is_primary and primary_set:
            is_primary = False
        if is_primary:
            primary_set = True
        cleaned.append({
            "id": mid,
            "name": name,
            "model": model_id,
            "enabled": enabled,
            "is_primary": is_primary,
        })
    # 没有 primary 就把第一个 enabled 的置为 primary
    if not primary_set:
        for m in cleaned:
            if m["enabled"]:
                m["is_primary"] = True
                break
    _set_raw("ocr_models", cleaned)


def reset_ocr_models() -> None:
    """重置 OCR 模型列表为默认 seed（用 config.LLM_MODEL 作为 primary）。

    用于切换默认模型后让设置页生效，或修复历史误配置。
    """
    cfg = get_config()
    seed = _seed_ocr_models()
    seed[0]["model"] = get_runtime_model("ocr") or cfg.LLM_MODEL
    _set_raw("ocr_models", seed)


def get_primary_ocr_model() -> Optional[Dict[str, Any]]:
    """返回当前 primary OCR 模型（dict），无则 None。"""
    for m in get_ocr_models():
        if m.get("is_primary") and m.get("enabled"):
            return m
    # 全部禁用时回退第一个
    models = get_ocr_models()
    return models[0] if models else None


def get_enabled_ocr_models() -> List[Dict[str, Any]]:
    """返回所有 enabled 的 OCR 模型，primary 在前。"""
    models = get_ocr_models()
    enabled = [m for m in models if m.get("enabled")]
    # primary 排第一
    enabled.sort(key=lambda m: 0 if m.get("is_primary") else 1)
    return enabled


def get_ocr_model_by_id(model_id: str) -> Optional[Dict[str, Any]]:
    """按 id 查找 OCR 模型。"""
    for m in get_ocr_models():
        if m.get("id") == model_id:
            return m
    return None


def get_link_params() -> Dict[str, Any]:
    val = _get_raw("link_params")
    if val is None:
        val = _seed_link_params()
        _set_raw("link_params", val)
    return val  # type: ignore[return-value]


def set_link_params(params: Dict[str, Any]) -> None:
    cur = get_link_params()
    cur.update(params)
    _set_raw("link_params", cur)


def get_ui_prefs() -> Dict[str, Any]:
    val = _get_raw("ui")
    if val is None:
        val = {"theme": "dark", "device_override": "auto"}
        _set_raw("ui", val)
    return val  # type: ignore[return-value]


def set_ui_prefs(prefs: Dict[str, Any]) -> None:
    cur = get_ui_prefs()
    cur.update(prefs)
    _set_raw("ui", cur)


def get_all_settings() -> Dict[str, Any]:
    """一次性返回全部设置（供前端设置页渲染）。"""
    return {
        "watch_folders": get_watch_folders(),
        "model": get_model_config(),
        "ocr_models": get_ocr_models(),
        "relay": get_relay_config(),
        "link_params": get_link_params(),
        "ui": get_ui_prefs(),
    }


# ---------------------------------------------------------------------------
# 监听文件夹的便捷操作
# ---------------------------------------------------------------------------
def add_watch_folder(path: str, device: str, app: str, recursive: bool = True, auto: bool = False) -> Dict[str, Any]:
    """手动新增一个监听文件夹。"""
    folders = get_watch_folders()
    # 去重：同路径不重复添加
    abs_path = normalize_abs_watch_path(path)
    for f in folders:
        if f["path"] == abs_path:
            # 已存在则更新元数据
            f["device"] = device
            f["app"] = app
            f["enabled"] = True
            f["recursive"] = recursive
            set_watch_folders(folders)
            return f
    folder = {
        "id": uuid.uuid4().hex[:12],
        "path": abs_path,
        "device": device,
        "app": app,
        "enabled": True,
        "recursive": recursive,
        "auto": auto,
    }
    folders.append(folder)
    set_watch_folders(folders)
    return folder


def remove_watch_folder(folder_id: str) -> bool:
    folders = get_watch_folders()
    new_folders = [f for f in folders if f["id"] != folder_id]
    if len(new_folders) == len(folders):
        return False
    set_watch_folders(new_folders)
    return True


def toggle_watch_folder(folder_id: str, enabled: bool) -> bool:
    folders = get_watch_folders()
    found = False
    for f in folders:
        if f["id"] == folder_id:
            f["enabled"] = enabled
            found = True
    if found:
        set_watch_folders(folders)
    return found

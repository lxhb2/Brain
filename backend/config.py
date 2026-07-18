"""Brain 后端配置模块。

使用 pydantic-settings 管理所有配置项，支持环境变量覆盖。
提供 get_config() 单例，并在初始化时自动创建所需数据目录。
"""
from __future__ import annotations

import os
from functools import lru_cache
from pathlib import Path
from typing import Dict, Optional

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Brain 应用全局配置。"""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
        case_sensitive=False,
    )

    # —— 数据与缓存目录 ——
    SYNCED_NOTES_ROOT: str = "data/synced_notes"
    THUMBNAIL_DIR: str = "data/thumbnails"
    DB_PATH: str = "data/brain.db"

    # —— OpenAI / LLM 配置 ——
    OPENAI_API_KEY: Optional[str] = None
    OPENAI_BASE_URL: Optional[str] = None
    LLM_MODEL: str = "gpt-4o"
    EMBEDDING_MODEL: str = "text-embedding-3-small"
    EMBEDDING_DIM: int = 1536  # text-embedding-3-small 默认维度

    # —— 链接权重计算参数 ——
    LINK_ALPHA: float = 0.6   # 语义相似度权重
    LINK_BETA: float = 0.3    # 关键词 Jaccard 权重
    LINK_GAMMA: float = 0.1   # 时间衰减权重
    LINK_WEIGHT_THRESHOLD: float = 0.35

    # —— 监听目录：路径 -> {device, app} 元数据 ——
    # 默认为 SYNCED_NOTES_ROOT 下的若干子目录
    WATCH_DIRS: Dict[str, Dict[str, str]] = {
        "data/synced_notes/ipad-goodnotes": {"device": "ipad", "app": "goodnotes"},
        "data/synced_notes/android-notes": {"device": "android", "app": "notes"},
        "data/synced_notes/pc-onenote": {"device": "pc", "app": "onenote"},
        "data/synced_notes/camera-shots": {"device": "camera", "app": "camera"},
    }

    def ensure_dirs(self) -> None:
        """创建运行所需的数据目录（如果缺失）。"""
        for d in (self.SYNCED_NOTES_ROOT, self.THUMBNAIL_DIR,
                  os.path.dirname(self.DB_PATH) or "."):
            Path(d).mkdir(parents=True, exist_ok=True)
        # 同时确保每个监听目录存在，便于扫描与监听
        # 优先用 settings_store 里持久化的文件夹；回退到 env 默认
        for watch_path in self.WATCH_DIRS.keys():
            Path(watch_path).mkdir(parents=True, exist_ok=True)


def get_watch_dirs_runtime() -> Dict[str, Dict[str, str]]:
    """返回运行时生效的监听目录映射 {abs_path: {device, app}}。

    优先读取 settings_store 中持久化且 enabled 的文件夹；
    若 settings_store 不可用（DB 未初始化），回退到 env 默认。
    """
    try:
        import settings_store  # 惰性导入，避免循环依赖
        folders = settings_store.get_watch_folders()
        result: Dict[str, Dict[str, str]] = {}
        for f in folders:
            if not f.get("enabled", True):
                continue
            result[f["path"]] = {"device": f.get("device", ""), "app": f.get("app", "")}
        return result if result else get_config().WATCH_DIRS
    except Exception:
        return get_config().WATCH_DIRS


def get_link_params_runtime() -> Dict[str, float]:
    """返回运行时生效的链接权重参数。"""
    try:
        import settings_store
        return settings_store.get_link_params()
    except Exception:
        cfg = get_config()
        return {
            "alpha": cfg.LINK_ALPHA,
            "beta": cfg.LINK_BETA,
            "gamma": cfg.LINK_GAMMA,
            "threshold": cfg.LINK_WEIGHT_THRESHOLD,
        }


@lru_cache(maxsize=1)
def get_config() -> Settings:
    """返回全局 Settings 单例，并确保数据目录已创建。"""
    cfg = Settings()
    cfg.ensure_dirs()
    return cfg

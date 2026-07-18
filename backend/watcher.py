"""文件系统监听器（watchdog）。

NoteWatcher(device_meta): FileSystemEventHandler 子类，处理 on_created /
on_modified / on_moved，带去抖、扩展名校验、hash 去重、入队逻辑。
start_watcher(): 对每个 WATCH_DIR 递归调度一个 Observer，返回所有 observer。
"""
from __future__ import annotations

import logging
import os
import threading
import time
from typing import Dict, List, Optional

from watchdog.events import FileSystemEventHandler
from watchdog.observers import Observer

import database
import ocr_processor
import scheduler
from config import get_watch_dirs_runtime

logger = logging.getLogger("brain.watcher")

SUPPORTED_EXTS = (".pdf", ".png", ".jpg", ".jpeg")
# 去抖窗口（秒）
_DEBOUNCE_SECONDS = 2.0


def _is_temp_or_hidden(fname: str) -> bool:
    """跳过临时/隐藏文件。"""
    if not fname:
        return True
    if fname.startswith(".") or fname.startswith("~"):
        return True
    if fname.endswith(".tmp") or fname.endswith(".swp") or fname.endswith(".part"):
        return True
    return False


class NoteWatcher(FileSystemEventHandler):
    """单目录的文件事件处理器，绑定一组 device/app 元数据。"""

    def __init__(self, device_meta: Dict[str, str]) -> None:
        super().__init__()
        self.device = device_meta.get("device")
        self.app = device_meta.get("app")
        # 路径 -> 最近处理时间戳，用于去抖
        self._last_seen: Dict[str, float] = {}
        self._lock = threading.Lock()

    # ---- 核心处理 ----
    def _handle_path(self, src_path: str) -> None:
        """对落到监听目录的文件做入库 + 入队。"""
        if not src_path or not os.path.exists(src_path):
            return
        fname = os.path.basename(src_path)
        if _is_temp_or_hidden(fname):
            return
        ext = os.path.splitext(fname)[1].lower()
        if ext not in SUPPORTED_EXTS:
            return

        # 去抖：同一文件短时间内只处理一次
        now = time.time()
        with self._lock:
            last = self._last_seen.get(src_path, 0.0)
            if now - last < _DEBOUNCE_SECONDS:
                return
            self._last_seen[src_path] = now

        try:
            file_hash = ocr_processor.compute_file_hash(src_path)
        except Exception as e:
            logger.warning("计算哈希失败 %s: %s", src_path, e)
            return

        # 去重：路径或哈希已存在则跳过
        existing = database.get_note_by_path(src_path)
        if existing:
            # 已存在且 done，不重处理；pending/failed 则重新入队
            if existing.get("status") not in ("done", "processing"):
                scheduler.enqueue_note(existing["id"])
            return

        note_id = database.insert_note(
            file_path=src_path,
            file_hash=file_hash,
            source_device=self.device,
            source_app=self.app,
            status="pending",
        )
        if note_id is None:
            return
        # 再次确认（hash 命中既有记录）
        note = database.get_note(note_id)
        if note and note.get("status") == "done":
            return
        logger.info("watcher 发现新文件: %s (note_id=%s)", src_path, note_id)
        scheduler.enqueue_note(note_id)

    # ---- watchdog 回调 ----
    def on_created(self, event) -> None:  # type: ignore[override]
        if event.is_directory:
            return
        self._handle_path(event.src_path)

    def on_modified(self, event) -> None:  # type: ignore[override]
        if event.is_directory:
            return
        self._handle_path(event.src_path)

    def on_moved(self, event) -> None:  # type: ignore[override]
        if event.is_directory:
            return
        # 移动事件：把旧路径的笔记 file_path 更新为新路径
        new_path = event.dest_path
        if not new_path or _is_temp_or_hidden(os.path.basename(new_path)):
            return
        ext = os.path.splitext(new_path)[1].lower()
        if ext not in SUPPORTED_EXTS:
            return
        # 尝试更新既有记录的路径
        # 注意：src_path 在 on_moved 时可能已不存在，这里只处理 dest
        self._handle_path(new_path)


_observers: List[Observer] = []


def _schedule_one(watch_path: str, meta: Dict[str, str], observers: List[Observer]) -> None:
    """为单个目录创建并启动一个 observer。"""
    if not os.path.isdir(watch_path):
        try:
            os.makedirs(watch_path, exist_ok=True)
        except Exception as e:
            logger.warning("无法创建监听目录 %s: %s", watch_path, e)
            return
    handler = NoteWatcher(device_meta=meta)
    obs = Observer()
    try:
        obs.schedule(handler, watch_path, recursive=True)
        obs.start()
        observers.append(obs)
        logger.info("已监听目录: %s (%s)", watch_path, meta)
    except Exception as e:
        logger.error("启动 observer 失败 %s: %s", watch_path, e)


def start_watcher() -> List[Observer]:
    """对每个监听目录递归调度一个 Observer。幂等：重复调用会返回已运行实例。

    监听目录来源：settings_store 中持久化且 enabled 的文件夹（运行时可配置）。
    """
    global _observers
    if _observers:
        return _observers

    watch_dirs = get_watch_dirs_runtime()
    observers: List[Observer] = []
    for watch_path, meta in watch_dirs.items():
        _schedule_one(watch_path, meta, observers)

    _observers = observers
    return observers


def reconfigure_watcher() -> List[Observer]:
    """设置变更后重载监听目录：停止旧 observer，按最新配置重启。

    用于前端新增/删除/启停文件夹后即时生效。
    """
    stop_watcher()
    return start_watcher()


def stop_watcher() -> None:
    """停止所有 observer（用于优雅关闭 / 重配置）。"""
    global _observers
    for obs in _observers:
        try:
            obs.stop()
        except Exception:
            pass
    for obs in _observers:
        try:
            obs.join(timeout=2.0)
        except Exception:
            pass
    _observers = []

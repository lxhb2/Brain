"""定时调度与后台处理 worker。

- start_scheduler(): 启动 APScheduler，每天 03:00 执行 full_scan()
- full_scan(): 遍历所有 WATCH_DIRS，对新文件入队待处理
- 处理队列（queue.Queue）+ 后台 worker 线程：消费 note_id 调用 ocr_processor
- enqueue_note(note_id): 把笔记 id 投入队列
- start_worker(): 启动 worker 线程
"""
from __future__ import annotations

import logging
import os
import queue
import threading
from typing import List, Optional

import database
import ocr_processor
from config import get_watch_dirs_runtime

logger = logging.getLogger("brain.scheduler")

SUPPORTED_EXTS = (".pdf", ".png", ".jpg", ".jpeg")

# 全局处理队列与状态
_processing_queue: "queue.Queue[int]" = queue.Queue()
_worker_thread: Optional[threading.Thread] = None
_worker_stop = threading.Event()
_scheduler: Optional[object] = None  # 防止类型依赖，运行时为 BackgroundScheduler


# ---------------------------------------------------------------------------
# 队列与 worker
# ---------------------------------------------------------------------------
def enqueue_note(note_id: int) -> None:
    """把笔记 id 投入处理队列（去重由 worker 端通过状态判断）。"""
    _processing_queue.put(int(note_id))


def queue_size() -> int:
    """返回当前队列长度。"""
    return _processing_queue.qsize()


def _worker_loop() -> None:
    """后台 worker 主循环：拉取 note_id 并处理。"""
    logger.info("OCR worker 已启动")
    while not _worker_stop.is_set():
        try:
            note_id = _processing_queue.get(timeout=1.0)
        except queue.Empty:
            continue
        try:
            note = database.get_note(note_id)
            # 跳过已 done 的，避免重复处理
            if note and note.get("status") == "done":
                _processing_queue.task_done()
                continue
            ocr_processor.process_note(note_id)
        except Exception as e:
            logger.exception("worker 处理笔记 %s 失败: %s", note_id, e)
            try:
                database.update_note_status(note_id, "failed")
            except Exception:
                pass
        finally:
            _processing_queue.task_done()
    logger.info("OCR worker 已停止")


def start_worker() -> None:
    """启动后台 worker 线程（幂等）。"""
    global _worker_thread
    if _worker_thread and _worker_thread.is_alive():
        return
    _worker_stop.clear()
    _worker_thread = threading.Thread(target=_worker_loop, name="brain-ocr-worker", daemon=True)
    _worker_thread.start()


def stop_worker() -> None:
    """通知 worker 停止（用于优雅关闭）。"""
    _worker_stop.set()


# ---------------------------------------------------------------------------
# 全量扫描
# ---------------------------------------------------------------------------
def _match_watch_meta(path: str) -> Optional[dict]:
    """根据文件路径匹配运行时监听目录中的 device/app 元数据。"""
    norm = os.path.normpath(path)
    for watch_path, meta in get_watch_dirs_runtime().items():
        wnorm = os.path.normpath(watch_path)
        if norm == wnorm or norm.startswith(wnorm + os.sep):
            return dict(meta)
    return None


def full_scan() -> int:
    """遍历所有监听目录，把尚未入库的笔记文件入库为 pending 并入队。

    监听目录来源：settings_store 中持久化且 enabled 的文件夹（运行时可配置）。
    返回新加入队列的笔记数量。
    """
    new_count = 0
    for watch_path, meta in get_watch_dirs_runtime().items():
        if not os.path.isdir(watch_path):
            continue
        for root, _dirs, files in os.walk(watch_path):
            for fname in files:
                if _is_temp_or_hidden(fname):
                    continue
                ext = os.path.splitext(fname)[1].lower()
                if ext not in SUPPORTED_EXTS:
                    continue
                fpath = os.path.join(root, fname)
                try:
                    file_hash = ocr_processor.compute_file_hash(fpath)
                except Exception as e:
                    logger.warning("计算哈希失败 %s: %s", fpath, e)
                    continue
                # 已存在（按 path 或 hash）则跳过
                existing = database.get_note_by_path(fpath)
                if existing:
                    continue
                note_id = database.insert_note(
                    file_path=fpath,
                    file_hash=file_hash,
                    source_device=meta.get("device"),
                    source_app=meta.get("app"),
                    status="pending",
                )
                if note_id is None:
                    continue
                # 重新检查是否其实已 done（hash 命中既有记录）
                note = database.get_note(note_id)
                if note and note.get("status") == "done":
                    continue
                enqueue_note(note_id)
                new_count += 1
    logger.info("full_scan 完成，新入队 %d 条", new_count)
    return new_count


def _is_temp_or_hidden(fname: str) -> bool:
    """判断是否是临时/隐藏文件（以 . 或 ~ 开头，或 .tmp 结尾）。"""
    if not fname:
        return True
    if fname.startswith(".") or fname.startswith("~"):
        return True
    if fname.endswith(".tmp") or fname.endswith(".swp") or fname.endswith(".part"):
        return True
    return False


# ---------------------------------------------------------------------------
# 调度器
# ---------------------------------------------------------------------------
def start_scheduler() -> None:
    """启动 APScheduler，注册每日 03:00 的 full_scan 任务。幂等。"""
    global _scheduler
    if _scheduler is not None:
        return
    try:
        from apscheduler.schedulers.background import BackgroundScheduler
        from apscheduler.triggers.cron import CronTrigger
    except ImportError as e:  # pragma: no cover
        logger.error("apscheduler 未安装: %s", e)
        return

    sched = BackgroundScheduler(timezone="UTC")
    sched.add_job(
        full_scan,
        trigger=CronTrigger(hour=3, minute=0),
        id="brain_full_scan",
        replace_existing=True,
        misfire_grace_time=3600,
    )
    # 可选：每日候选链接衰减（简化版，复用 full_scan 时段）
    # 这里不做额外任务，保持简单
    sched.start()
    _scheduler = sched
    logger.info("APScheduler 已启动，每日 03:00 UTC 执行 full_scan")


def stop_scheduler() -> None:
    """关闭调度器（用于优雅关闭）。"""
    global _scheduler
    if _scheduler is not None:
        try:
            _scheduler.shutdown(wait=False)
        except Exception:
            pass
        _scheduler = None

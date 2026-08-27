"""定时调度与后台处理 worker。

定时任务（均使用 Asia/Shanghai 时区）：
  - 每日 03:00 full_scan：扫描监听目录新文件
  - 每日 23:00 daily_summary：把今天的笔记交给 LLM 生成归纳
  - 每日 03:30 decay：链接权重衰减 + 记忆权重衰减
  - 每小时 retry_failed：自动重试失败的 OCR（最多 3 次）

后台 worker：
  - 队列消费 note_id，调用 ocr_processor.process_note
  - 失败时自动 increment_retry_count 并置 failed
"""
from __future__ import annotations

import logging
import os
import queue
import threading
from datetime import datetime, timezone, timedelta
from typing import Dict, List, Optional

import database
import growth
import ocr_processor
from config import get_config, get_watch_dirs_runtime

logger = logging.getLogger("brain.scheduler")

# 国内时区（避免依赖 zoneinfo）
_TZ_SHANGHAI = timezone(timedelta(hours=8))

SUPPORTED_EXTS = (".pdf", ".png", ".jpg", ".jpeg", ".txt", ".md", ".markdown", ".docx")

# 全局处理队列与状态
_processing_queue: "queue.Queue[int]" = queue.Queue()
_worker_threads: List[threading.Thread] = []
_worker_stop = threading.Event()
_scheduler: Optional[object] = None  # 防止类型依赖，运行时为 BackgroundScheduler
# 正在处理中的 note_id 集合，防止多 worker 重复拾取同一条
_processing_ids: set = set()
_processing_ids_lock = threading.Lock()


# ---------------------------------------------------------------------------
# 队列与 worker
# ---------------------------------------------------------------------------
def enqueue_note(note_id: int) -> None:
    """把笔记 id 投入处理队列（去重由 worker 端通过状态判断）。"""
    _processing_queue.put(int(note_id))


def queue_size() -> int:
    """返回当前队列长度。"""
    return _processing_queue.qsize()


def _worker_loop(worker_idx: int) -> None:
    """后台 worker 主循环：拉取 note_id 并处理。

    多 worker 并发运行，通过 _processing_ids 集合去重，避免同一 note_id
    被多个 worker 同时拾取（enqueue 可能被调用多次）。
    """
    logger.info("OCR worker #%d 已启动", worker_idx)
    while not _worker_stop.is_set():
        try:
            note_id = _processing_queue.get(timeout=1.0)
        except queue.Empty:
            continue
        # 去重：正在处理中的跳过
        with _processing_ids_lock:
            if note_id in _processing_ids:
                continue
            _processing_ids.add(note_id)
        try:
            note = database.get_note(note_id)
            # 跳过已 done 的，避免重复处理
            if note and note.get("status") == "done":
                continue
            ocr_processor.process_note(note_id)
        except Exception as e:
            err_msg = str(e)
            logger.exception("worker #%d 处理笔记 %s 失败: %s", worker_idx, note_id, e)
            try:
                # 记录重试次数和错误信息，便于自动重试和前端展示
                database.increment_retry_count(note_id, err_msg)
                database.update_note_status(note_id, "failed")
            except Exception:
                pass
        finally:
            with _processing_ids_lock:
                _processing_ids.discard(note_id)
            _processing_queue.task_done()
    logger.info("OCR worker #%d 已停止", worker_idx)


def start_worker() -> None:
    """启动后台 worker 线程池（幂等）。

    worker 数量由 config.OCR_WORKERS 控制，默认 3。
    多个 worker 并行消费队列，一次可同时 OCR 多张笔记。
    """
    global _worker_threads
    if _worker_threads and any(t.is_alive() for t in _worker_threads):
        return
    _worker_stop.clear()
    _worker_threads = []
    try:
        from config import get_config
        n_workers = max(1, get_config().OCR_WORKERS)
    except Exception:
        n_workers = 3
    for i in range(n_workers):
        t = threading.Thread(target=_worker_loop, args=(i,), name=f"brain-ocr-worker-{i}", daemon=True)
        t.start()
        _worker_threads.append(t)
    logger.info("已启动 %d 个 OCR worker", n_workers)


def stop_worker() -> None:
    """通知所有 worker 停止（用于优雅关闭）。"""
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
        referenced_images = ocr_processor.markdown_referenced_images(watch_path)
        for root, _dirs, files in os.walk(watch_path):
            for fname in files:
                if _is_temp_or_hidden(fname):
                    continue
                ext = os.path.splitext(fname)[1].lower()
                if ext not in SUPPORTED_EXTS:
                    continue
                fpath = os.path.join(root, fname)
                if ext in ocr_processor.IMAGE_EXTS and os.path.abspath(fpath) in referenced_images:
                    continue
                if database.is_ignored_file(fpath):
                    logger.info("文件在忽略名单中，跳过入库: %s", fpath)
                    continue
                try:
                    file_hash = ocr_processor.compute_file_hash(fpath)
                except Exception as e:
                    logger.warning("计算哈希失败 %s: %s", fpath, e)
                    continue
                if database.is_ignored_file(fpath, file_hash):
                    logger.info("文件哈希在忽略名单中，跳过入库: %s", fpath)
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
                meta = meta or {}
                fname = os.path.basename(fpath)
                database.insert_activity(
                    event_type="upload",
                    message=f"扫描发现 {meta.get('device', 'unknown')}-{meta.get('app', 'unknown')} 文件 {fname}",
                    device=meta.get("device"),
                    app=meta.get("app"),
                    note_id=note_id,
                    file_name=fname,
                )
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
# 每日归纳
# ---------------------------------------------------------------------------
def generate_daily_summary(target_date: Optional[str] = None) -> Optional[Dict[str, int]]:
    """生成某天的笔记归纳，存入 daily_summaries 表。

    Args:
        target_date: YYYY-MM-DD 格式。None 表示今天（Asia/Shanghai）。
    """
    if target_date is None:
        target_date = datetime.now(_TZ_SHANGHAI).strftime("%Y-%m-%d")

    notes = database.list_notes_by_date(target_date)
    if not notes:
        logger.info("每日归纳：%s 无 done 笔记，跳过", target_date)
        return None

    note_ids = [n["id"] for n in notes]
    # 拼接笔记摘要给 LLM
    notes_text_parts = []
    for n in notes:
        title = n.get("title") or "(未命名)"
        summary = (n.get("summary") or "").strip()
        ocr = (n.get("ocr_text") or "").strip()
        if len(ocr) > 300:
            ocr = ocr[:300] + "..."
        notes_text_parts.append(f"#{n['id']} {title}\n摘要：{summary}\n内容：{ocr}")
    notes_text = "\n\n".join(notes_text_parts)[:6000]  # 截断防止超长

    client = ocr_processor._get_client()
    if client is None:
        logger.warning("每日归纳：无 LLM 客户端，跳过")
        return None

    cfg = ocr_processor.get_config()
    prompt = (
        f"以下是用户在 {target_date} 录入的 {len(notes)} 条笔记。"
        "请生成一份简洁的当日归纳：\n"
        "1. 今日学习/记录的主要主题（1-3 个关键词）\n"
        "2. 每条笔记的核心要点（1 句话）\n"
        "3. 笔记之间的关联或主题归类（如有）\n\n"
        f"笔记内容：\n{notes_text}"
    )

    try:
        resp = client.chat.completions.create(
            model=cfg.QA_MODEL or cfg.LLM_MODEL,
            messages=[{"role": "user", "content": prompt}],
            temperature=0.3,
            max_tokens=3000,
            timeout=180,
        )
        content = (resp.choices[0].message.content or "").strip()
        if not content:
            logger.warning("每日归纳：LLM 返回空内容")
            return None
        summary_id = database.upsert_daily_summary(target_date, content, note_ids)
        cfg = get_config()
        database.insert_activity(
            event_type="model",
            message=f"{cfg.QA_MODEL or cfg.LLM_MODEL} 完成每日归纳，覆盖 {len(notes)} 条笔记",
            model=cfg.QA_MODEL or cfg.LLM_MODEL,
        )
        logger.info("每日归纳完成：%s 共 %d 条笔记，归纳 id=%s",
                    target_date, len(notes), summary_id)
        return {"summary_id": summary_id, "notes_count": len(notes)}
    except Exception as e:
        logger.exception("每日归纳失败：%s", e)
        return None


# ---------------------------------------------------------------------------
# 自动重试失败的 OCR
# ---------------------------------------------------------------------------
MAX_RETRIES = 3


def retry_failed_ocr() -> int:
    """自动重试失败的 OCR（最多 MAX_RETRIES 次）。

    返回重新入队的目标数。
    """
    failed = database.list_failed_notes_for_retry(max_retries=MAX_RETRIES, limit=50)
    if not failed:
        return 0
    count = 0
    for n in failed:
        try:
            database.update_note_status(n["id"], "pending")
            enqueue_note(n["id"])
            count += 1
        except Exception as e:
            logger.warning("重试入队失败 note_id=%s: %s", n["id"], e)
    logger.info("自动重试：%d 条失败笔记重新入队", count)
    return count


# ---------------------------------------------------------------------------
# 调度器
# ---------------------------------------------------------------------------
def start_scheduler() -> None:
    """启动 APScheduler，注册定时任务。幂等。

    所有任务使用 Asia/Shanghai 时区：
      - 03:00 full_scan（扫描新文件）
      - 03:30 decay（衰减链接权重 + 记忆权重）
      - 23:00 daily_summary（生成今日归纳）
      - 每小时 retry_failed_ocr（自动重试失败 OCR）
    """
    global _scheduler
    if _scheduler is not None:
        return
    try:
        from apscheduler.schedulers.background import BackgroundScheduler
        from apscheduler.triggers.cron import CronTrigger
    except ImportError as e:  # pragma: no cover
        logger.error("apscheduler 未安装: %s", e)
        return

    sched = BackgroundScheduler(timezone=_TZ_SHANGHAI)

    # 每日 03:00 全量扫描
    sched.add_job(
        full_scan,
        trigger=CronTrigger(hour=3, minute=0),
        id="brain_full_scan",
        replace_existing=True,
        misfire_grace_time=3600,
    )

    # 每日 03:30 记忆/链接衰减
    def _decay_job():
        try:
            link_result = database.decay_link_weights(decay_factor=0.95, min_weight=0.1)
            mem_result = database.decay_memory_weights(decay_factor=0.98, min_weight=0.2)
            logger.info("衰减完成：链接 %s，记忆 %s", link_result, mem_result)
        except Exception as e:
            logger.exception("衰减任务失败：%s", e)

    sched.add_job(
        _decay_job,
        trigger=CronTrigger(hour=3, minute=30),
        id="brain_decay",
        replace_existing=True,
        misfire_grace_time=3600,
    )

    # 每日 23:00 生成今日归纳
    sched.add_job(
        generate_daily_summary,
        trigger=CronTrigger(hour=23, minute=0),
        id="brain_daily_summary",
        replace_existing=True,
        misfire_grace_time=3600,
    )

    # 每日 23:05 分诊少量积压笔记，并生成成长审核
    def _growth_job():
        try:
            result = growth.run_daily_maintenance()
            logger.info("每日成长维护完成：%s", result)
        except Exception as e:
            logger.exception("每日成长维护失败：%s", e)

    sched.add_job(
        _growth_job,
        trigger=CronTrigger(hour=23, minute=5),
        id="brain_growth_maintenance",
        replace_existing=True,
        misfire_grace_time=3600,
    )

    # 每日 02:30 自动备份数据库；备份函数自身会写活动日志
    def _backup_job():
        try:
            result = database.create_database_backup()
            logger.info("自动备份完成: %s", result["file_name"])
        except Exception as e:
            logger.exception("自动备份失败：%s", e)

    sched.add_job(
        _backup_job,
        trigger=CronTrigger(hour=2, minute=30),
        id="brain_daily_backup",
        replace_existing=True,
        misfire_grace_time=3600,
    )

    # 每小时重试失败的 OCR
    sched.add_job(
        retry_failed_ocr,
        trigger=CronTrigger(minute=15),  # 每小时第 15 分钟
        id="brain_retry_failed",
        replace_existing=True,
        misfire_grace_time=600,
    )

    sched.start()
    _scheduler = sched
    logger.info(
        "APScheduler 已启动 (Asia/Shanghai)：02:30 备份 / 03:00 全量扫描 / 03:30 衰减 / "
        "23:00 每日归纳 / 23:05 成长维护 / 每小时重试失败"
    )


def stop_scheduler() -> None:
    """关闭调度器（用于优雅关闭）。"""
    global _scheduler
    if _scheduler is not None:
        try:
            _scheduler.shutdown(wait=False)
        except Exception:
            pass
        _scheduler = None

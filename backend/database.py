"""Brain 数据访问层。

使用标准库 sqlite3 实现，包含 4 张表（notes/links/qa_history/feedback）
及索引。embedding 以 JSON 字符串数组形式存储在 TEXT 列中（便于调试与
跨平台兼容），并提供内存态余弦相似度检索。所有写操作通过同一把全局
锁串行化，连接使用 check_same_thread=False 以支持多线程（监听 / 调度 /
工作线程）。
"""
from __future__ import annotations

import json
import logging
import math
import sqlite3
import threading
from contextlib import contextmanager
from datetime import datetime, timezone
from typing import Any, Dict, Iterator, List, Optional, Sequence, Tuple

from config import get_config

logger = logging.getLogger("brain.database")

# 全局写锁，保护 SQLite 并发写
_db_lock = threading.RLock()


# ---------------------------------------------------------------------------
# 连接与初始化
# ---------------------------------------------------------------------------
@contextmanager
def get_conn() -> Iterator[sqlite3.Connection]:
    """获取一个 SQLite 连接的上下文管理器，自动提交/回滚并关闭。

    使用 Row 工厂，使结果可按列名访问。
    """
    cfg = get_config()
    conn = sqlite3.connect(cfg.DB_PATH, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL;")
    conn.execute("PRAGMA foreign_keys=ON;")
    try:
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def init_db() -> None:
    """创建所有表与索引（幂等）。"""
    with _db_lock, get_conn() as conn:
        c = conn.cursor()
        c.execute(
            """
            CREATE TABLE IF NOT EXISTS notes (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                file_path TEXT UNIQUE NOT NULL,
                title TEXT,
                ocr_text TEXT,
                summary TEXT,
                keywords TEXT,
                source_device TEXT,
                source_app TEXT,
                status TEXT DEFAULT 'pending',
                embedding TEXT,
                thumbnail_path TEXT,
                file_hash TEXT,
                created_at TEXT NOT NULL,
                processed_at TEXT
            );
            """
        )
        c.execute("CREATE INDEX IF NOT EXISTS idx_notes_status ON notes(status);")
        c.execute("CREATE INDEX IF NOT EXISTS idx_notes_source ON notes(source_device, source_app);")
        c.execute("CREATE INDEX IF NOT EXISTS idx_notes_file_hash ON notes(file_hash);")

        c.execute(
            """
            CREATE TABLE IF NOT EXISTS links (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                source_note_id INTEGER NOT NULL,
                target_note_id INTEGER NOT NULL,
                weight REAL NOT NULL,
                reason TEXT,
                link_type TEXT,
                created_at TEXT NOT NULL,
                FOREIGN KEY (source_note_id) REFERENCES notes(id),
                FOREIGN KEY (target_note_id) REFERENCES notes(id),
                UNIQUE(source_note_id, target_note_id, link_type)
            );
            """
        )

        c.execute(
            """
            CREATE TABLE IF NOT EXISTS qa_history (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                question TEXT NOT NULL,
                answer TEXT,
                citations TEXT,
                created_at TEXT NOT NULL
            );
            """
        )

        c.execute(
            """
            CREATE TABLE IF NOT EXISTS feedback (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                qa_id INTEGER NOT NULL,
                rating TEXT NOT NULL,
                correction TEXT,
                created_at TEXT NOT NULL,
                FOREIGN KEY (qa_id) REFERENCES qa_history(id)
            );
            """
        )

        # —— 运行时可配置的设置（key-value，value 为 JSON 字符串）——
        # 支持：watch_folders / model / relay / link_params 等
        c.execute(
            """
            CREATE TABLE IF NOT EXISTS settings (
                key TEXT PRIMARY KEY,
                value TEXT NOT NULL,
                updated_at TEXT NOT NULL
            );
            """
        )

        # —— 兼容性迁移：给 notes 表添加 ocr_model 字段（记录用了哪个模型 OCR）——
        # 旧库不存在该列时通过 ALTER TABLE 添加；新库在 CREATE TABLE 已包含则跳过
        try:
            c.execute("SELECT ocr_model FROM notes LIMIT 0;")
        except sqlite3.OperationalError:
            logger.info("迁移：为 notes 表添加 ocr_model 列")
            c.execute("ALTER TABLE notes ADD COLUMN ocr_model TEXT;")


# ---------------------------------------------------------------------------
# 工具函数
# ---------------------------------------------------------------------------
def _now() -> str:
    """返回 ISO8601 UTC 时间字符串。"""
    return datetime.now(timezone.utc).isoformat()


def _row_to_dict(row: Optional[sqlite3.Row]) -> Optional[Dict[str, Any]]:
    """把 sqlite3.Row 转成普通 dict。"""
    if row is None:
        return None
    d = dict(row)
    # 反序列化 JSON 字段，方便上层使用
    if "keywords" in d and isinstance(d["keywords"], str):
        try:
            d["keywords"] = json.loads(d["keywords"])
        except (json.JSONDecodeError, TypeError):
            d["keywords"] = []
    if "embedding" in d and isinstance(d["embedding"], str):
        try:
            d["embedding"] = json.loads(d["embedding"])
        except (json.JSONDecodeError, TypeError):
            d["embedding"] = None
    return d


# ---------------------------------------------------------------------------
# notes CRUD
# ---------------------------------------------------------------------------
def insert_note(
    *,
    file_path: str,
    file_hash: Optional[str] = None,
    source_device: Optional[str] = None,
    source_app: Optional[str] = None,
    title: Optional[str] = None,
    status: str = "pending",
) -> Optional[int]:
    """插入一条 pending 笔记。若 file_path 已存在则返回已存在的 id（去重）。

    返回 note id；当因唯一约束冲突时返回既有记录的 id。
    """
    with _db_lock, get_conn() as conn:
        cur = conn.cursor()
        # 先按 file_path 去重
        cur.execute("SELECT id FROM notes WHERE file_path = ?;", (file_path,))
        existing = cur.fetchone()
        if existing:
            return int(existing["id"])
        # 按 file_hash 去重（同一文件被搬到不同路径）
        if file_hash:
            cur.execute("SELECT id FROM notes WHERE file_hash = ?;", (file_hash,))
            existing_hash = cur.fetchone()
            if existing_hash:
                return int(existing_hash["id"])
        try:
            cur.execute(
                """
                INSERT INTO notes
                    (file_path, file_hash, source_device, source_app, title, status, created_at)
                VALUES (?, ?, ?, ?, ?, ?, ?);
                """,
                (file_path, file_hash, source_device, source_app, title, status, _now()),
            )
            return int(cur.lastrowid)
        except sqlite3.IntegrityError:
            cur.execute("SELECT id FROM notes WHERE file_path = ?;", (file_path,))
            row = cur.fetchone()
            return int(row["id"]) if row else None


def update_note_status(note_id: int, status: str) -> None:
    """更新笔记状态。"""
    with _db_lock, get_conn() as conn:
        conn.execute(
            "UPDATE notes SET status = ? WHERE id = ?;",
            (status, note_id),
        )


def update_note_content(
    note_id: int,
    *,
    title: str,
    ocr_text: str,
    summary: str,
    keywords: List[str],
    embedding: Sequence[float],
    thumbnail_path: Optional[str] = None,
    status: str = "done",
    ocr_model: Optional[str] = None,
) -> None:
    """写入 OCR/结构化结果，并把状态置为 done。

    Args:
        ocr_model: 使用的 OCR 模型 id（settings_store 里的 id），用于追溯
    """
    with _db_lock, get_conn() as conn:
        # 检查 ocr_model 列是否存在（兼容旧库未迁移的场景）
        try:
            conn.execute(
                """
                UPDATE notes
                SET title = ?, ocr_text = ?, summary = ?, keywords = ?,
                    embedding = ?, thumbnail_path = ?, status = ?, processed_at = ?,
                    ocr_model = ?
                WHERE id = ?;
                """,
                (
                    title,
                    ocr_text,
                    summary,
                    json.dumps(keywords, ensure_ascii=False),
                    json.dumps(list(embedding)),
                    thumbnail_path,
                    status,
                    _now(),
                    ocr_model,
                    note_id,
                ),
            )
        except sqlite3.OperationalError:
            # 旧库没有 ocr_model 列，回退到不带该列的更新
            conn.execute(
                """
                UPDATE notes
                SET title = ?, ocr_text = ?, summary = ?, keywords = ?,
                    embedding = ?, thumbnail_path = ?, status = ?, processed_at = ?
                WHERE id = ?;
                """,
                (
                    title,
                    ocr_text,
                    summary,
                    json.dumps(keywords, ensure_ascii=False),
                    json.dumps(list(embedding)),
                    thumbnail_path,
                    status,
                    _now(),
                    note_id,
                ),
            )


def get_note(note_id: int) -> Optional[Dict[str, Any]]:
    """按 id 获取单条笔记（含所有字段）。"""
    with get_conn() as conn:
        row = conn.execute("SELECT * FROM notes WHERE id = ?;", (note_id,)).fetchone()
        return _row_to_dict(row)


def get_note_by_path(file_path: str) -> Optional[Dict[str, Any]]:
    """按文件路径获取笔记。"""
    with get_conn() as conn:
        row = conn.execute("SELECT * FROM notes WHERE file_path = ?;", (file_path,)).fetchone()
        return _row_to_dict(row)


def list_notes(
    *,
    device: Optional[str] = None,
    app: Optional[str] = None,
    q: Optional[str] = None,
    status: Optional[str] = None,
    limit: int = 50,
    offset: int = 0,
) -> List[Dict[str, Any]]:
    """按筛选条件分页列出笔记。

    q 模糊匹配 title / ocr_text / summary。
    """
    clauses: List[str] = []
    params: List[Any] = []
    if device:
        clauses.append("source_device = ?")
        params.append(device)
    if app:
        clauses.append("source_app = ?")
        params.append(app)
    if status:
        clauses.append("status = ?")
        params.append(status)
    if q:
        clauses.append("(title LIKE ? OR ocr_text LIKE ? OR summary LIKE ?)")
        like = f"%{q}%"
        params.extend([like, like, like])

    where = (" WHERE " + " AND ".join(clauses)) if clauses else ""
    sql = (
        f"SELECT * FROM notes{where} ORDER BY created_at DESC LIMIT ? OFFSET ?;"
    )
    params.extend([int(limit), int(offset)])
    with get_conn() as conn:
        rows = conn.execute(sql, params).fetchall()
        return [r for r in (_row_to_dict(row) for row in rows) if r is not None]


def count_notes(*, status: Optional[str] = None) -> int:
    """统计笔记总数（可按状态过滤）。"""
    sql = "SELECT COUNT(*) AS n FROM notes"
    params: List[Any] = []
    if status:
        sql += " WHERE status = ?"
        params.append(status)
    with get_conn() as conn:
        row = conn.execute(sql + ";", params).fetchone()
        return int(row["n"]) if row else 0


def get_done_notes_with_embeddings() -> List[Dict[str, Any]]:
    """返回所有 status='done' 且有 embedding 的笔记（用于链接计算与向量检索）。"""
    with get_conn() as conn:
        rows = conn.execute(
            """
            SELECT * FROM notes
            WHERE status = 'done' AND embedding IS NOT NULL
            ORDER BY created_at ASC;
            """
        ).fetchall()
        return [r for r in (_row_to_dict(row) for row in rows) if r is not None]


# ---------------------------------------------------------------------------
# links CRUD
# ---------------------------------------------------------------------------
def insert_link(
    *,
    source_note_id: int,
    target_note_id: int,
    weight: float,
    link_type: str,
    reason: Optional[str] = None,
) -> None:
    """插入或更新一条候选链接（按 (source, target, link_type) 去重，upsert 权重）。"""
    with _db_lock, get_conn() as conn:
        conn.execute(
            """
            INSERT INTO links (source_note_id, target_note_id, weight, reason, link_type, created_at)
            VALUES (?, ?, ?, ?, ?, ?)
            ON CONFLICT(source_note_id, target_note_id, link_type)
            DO UPDATE SET weight = excluded.weight, reason = excluded.reason, created_at = excluded.created_at;
            """,
            (source_note_id, target_note_id, float(weight), reason, link_type, _now()),
        )


def delete_links_for_note(note_id: int) -> None:
    """删除某条笔记参与的所有候选链接（用于重算前的清理）。"""
    with _db_lock, get_conn() as conn:
        conn.execute(
            "DELETE FROM links WHERE source_note_id = ? OR target_note_id = ?;",
            (note_id, note_id),
        )


def list_links() -> List[Dict[str, Any]]:
    """返回全部链接。"""
    with get_conn() as conn:
        rows = conn.execute("SELECT * FROM links ORDER BY weight DESC;").fetchall()
        return [dict(r) for r in rows]


def get_neighbors(note_id: int) -> List[Dict[str, Any]]:
    """获取与某笔记相邻的（节点 + 边）信息。"""
    with get_conn() as conn:
        edge_rows = conn.execute(
            """
            SELECT * FROM links
            WHERE source_note_id = ? OR target_note_id = ?
            ORDER BY weight DESC;
            """,
            (note_id, note_id),
        ).fetchall()
        edges = [dict(r) for r in edge_rows]
        neighbor_ids: set[int] = set()
        for e in edges:
            neighbor_ids.add(e["source_note_id"])
            neighbor_ids.add(e["target_note_id"])
        neighbor_ids.discard(note_id)
        if not neighbor_ids:
            return []
        placeholders = ",".join("?" for _ in neighbor_ids)
        rows = conn.execute(
            f"SELECT * FROM notes WHERE id IN ({placeholders});",
            tuple(neighbor_ids),
        ).fetchall()
        nodes = [r for r in (_row_to_dict(row) for row in rows) if r is not None]
        return [{"edge": e, "node": n} for e in edges for n in nodes
                if n and (n["id"] == e["source_note_id"] or n["id"] == e["target_note_id"])]


def get_links_between(note_ids: Sequence[int]) -> List[Dict[str, Any]]:
    """返回给定笔记集合两两之间的所有链接。"""
    if len(note_ids) < 2:
        return []
    placeholders = ",".join("?" for _ in note_ids)
    with get_conn() as conn:
        rows = conn.execute(
            f"""
            SELECT * FROM links
            WHERE source_note_id IN ({placeholders}) AND target_note_id IN ({placeholders});
            """,
            tuple(note_ids) + tuple(note_ids),
        ).fetchall()
        return [dict(r) for r in rows]


def adjust_link_weight(source_note_id: int, target_note_id: int, delta: float) -> None:
    """对一对笔记间所有链接权重做加性调整，并 clamp 到 [0,1]。"""
    with _db_lock, get_conn() as conn:
        conn.execute(
            """
            UPDATE links
            SET weight = MIN(1.0, MAX(0.0, weight + ?))
            WHERE (source_note_id = ? AND target_note_id = ?)
               OR (source_note_id = ? AND target_note_id = ?);
            """,
            (float(delta), source_note_id, target_note_id, target_note_id, source_note_id),
        )


# ---------------------------------------------------------------------------
# qa_history CRUD
# ---------------------------------------------------------------------------
def insert_qa(*, question: str, answer: str, citations: List[Dict[str, Any]]) -> int:
    """记录一次问答，返回 qa_history.id。"""
    with _db_lock, get_conn() as conn:
        cur = conn.cursor()
        cur.execute(
            """
            INSERT INTO qa_history (question, answer, citations, created_at)
            VALUES (?, ?, ?, ?);
            """,
            (question, answer, json.dumps(citations, ensure_ascii=False), _now()),
        )
        return int(cur.lastrowid)


def get_qa_history(limit: int = 50, offset: int = 0) -> List[Dict[str, Any]]:
    """返回问答历史。"""
    with get_conn() as conn:
        rows = conn.execute(
            "SELECT * FROM qa_history ORDER BY created_at DESC LIMIT ? OFFSET ?;",
            (int(limit), int(offset)),
        ).fetchall()
        out: List[Dict[str, Any]] = []
        for r in rows:
            d = dict(r)
            if isinstance(d.get("citations"), str):
                try:
                    d["citations"] = json.loads(d["citations"])
                except (json.JSONDecodeError, TypeError):
                    d["citations"] = []
            out.append(d)
        return out


def get_qa(qa_id: int) -> Optional[Dict[str, Any]]:
    """按 id 获取问答记录。"""
    with get_conn() as conn:
        row = conn.execute("SELECT * FROM qa_history WHERE id = ?;", (qa_id,)).fetchone()
        if row is None:
            return None
        d = dict(row)
        if isinstance(d.get("citations"), str):
            try:
                d["citations"] = json.loads(d["citations"])
            except (json.JSONDecodeError, TypeError):
                d["citations"] = []
        return d


# ---------------------------------------------------------------------------
# feedback CRUD
# ---------------------------------------------------------------------------
def insert_feedback(*, qa_id: int, rating: str, correction: Optional[str] = None) -> int:
    """记录一条反馈，返回 feedback.id。"""
    with _db_lock, get_conn() as conn:
        cur = conn.cursor()
        cur.execute(
            """
            INSERT INTO feedback (qa_id, rating, correction, created_at)
            VALUES (?, ?, ?, ?);
            """,
            (qa_id, rating, correction, _now()),
        )
        return int(cur.lastrowid)


# ---------------------------------------------------------------------------
# 向量检索（内存态余弦相似度）
# ---------------------------------------------------------------------------
def cosine_similarity(a: Sequence[float], b: Sequence[float]) -> float:
    """计算两个向量的余弦相似度。维度不一致或零向量时返回 0。"""
    if not a or not b or len(a) != len(b):
        return 0.0
    dot = 0.0
    na = 0.0
    nb = 0.0
    for x, y in zip(a, b):
        dot += x * y
        na += x * x
        nb += y * y
    if na <= 0.0 or nb <= 0.0:
        return 0.0
    return dot / (math.sqrt(na) * math.sqrt(nb))


def search_similar(query_vec: Sequence[float], top_k: int = 5) -> List[Dict[str, Any]]:
    """在全库 done 笔记中扫描，返回与查询向量最相似的 top_k 笔记。

    每条结果包含 note 字段（全部字段）与 score 字段（相似度）。
    """
    notes = get_done_notes_with_embeddings()
    scored: List[Tuple[float, Dict[str, Any]]] = []
    for n in notes:
        emb = n.get("embedding")
        if not emb:
            continue
        score = cosine_similarity(query_vec, emb)
        scored.append((score, n))
    scored.sort(key=lambda x: x[0], reverse=True)
    top = scored[: int(top_k)]
    return [{"score": s, "note": n} for s, n in top]


# ---------------------------------------------------------------------------
# 统计
# ---------------------------------------------------------------------------
def get_stats() -> Dict[str, Any]:
    """返回仪表盘统计信息。"""
    with get_conn() as conn:
        notes_total = conn.execute("SELECT COUNT(*) AS n FROM notes;").fetchone()["n"]
        notes_done = conn.execute("SELECT COUNT(*) AS n FROM notes WHERE status='done';").fetchone()["n"]
        notes_pending = conn.execute(
            "SELECT COUNT(*) AS n FROM notes WHERE status IN ('pending','processing');"
        ).fetchone()["n"]
        notes_failed = conn.execute("SELECT COUNT(*) AS n FROM notes WHERE status='failed';").fetchone()["n"]
        links_total = conn.execute("SELECT COUNT(*) AS n FROM links;").fetchone()["n"]
        qa_total = conn.execute("SELECT COUNT(*) AS n FROM qa_history;").fetchone()["n"]
        feedback_total = conn.execute("SELECT COUNT(*) AS n FROM feedback;").fetchone()["n"]
    return {
        "notes_total": int(notes_total),
        "notes_done": int(notes_done),
        "notes_pending": int(notes_pending),
        "notes_failed": int(notes_failed),
        "links_total": int(links_total),
        "qa_total": int(qa_total),
        "feedback_total": int(feedback_total),
        "queue_size": _queue_size(),
    }


def _queue_size() -> int:
    """读取调度器队列长度（避免循环导入，惰性获取）。"""
    try:
        from scheduler import queue_size  # 局部导入避免循环
        return queue_size()
    except Exception:
        return 0

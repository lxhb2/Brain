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

        # —— 兼容性迁移：notes.manually_edited（标记人工编辑过，重新 OCR 时保留人工修改）——
        try:
            c.execute("SELECT manually_edited FROM notes LIMIT 0;")
        except sqlite3.OperationalError:
            logger.info("迁移：为 notes 表添加 manually_edited 列")
            c.execute("ALTER TABLE notes ADD COLUMN manually_edited INTEGER DEFAULT 0;")

        # —— 兼容性迁移：notes.retry_count + last_error（OCR 失败重试）——
        try:
            c.execute("SELECT retry_count FROM notes LIMIT 0;")
        except sqlite3.OperationalError:
            logger.info("迁移：为 notes 表添加 retry_count / last_error 列")
            c.execute("ALTER TABLE notes ADD COLUMN retry_count INTEGER DEFAULT 0;")
            c.execute("ALTER TABLE notes ADD COLUMN last_error TEXT;")

        # —— 长期记忆表：存用户偏好、关键事实、修正过的知识点 ——
        # type: 'preference' | 'fact' | 'correction' | 'term'
        # content: 记忆内容（自然语言）
        # source: 来源（'feedback' | 'qa' | 'manual'）
        # weight: 权重 0-1，用于检索时排序
        c.execute(
            """
            CREATE TABLE IF NOT EXISTS user_memory (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                type TEXT NOT NULL,
                content TEXT NOT NULL,
                source TEXT,
                weight REAL DEFAULT 0.5,
                embedding TEXT,
                related_qa_id INTEGER,
                created_at TEXT NOT NULL,
                last_used_at TEXT,
                use_count INTEGER DEFAULT 0,
                FOREIGN KEY (related_qa_id) REFERENCES qa_history(id)
            );
            """
        )
        c.execute("CREATE INDEX IF NOT EXISTS idx_memory_type ON user_memory(type);")
        c.execute("CREATE INDEX IF NOT EXISTS idx_memory_weight ON user_memory(weight);")

        # —— qa_history 加 session_id（会话分组，用于多轮对话）——
        try:
            c.execute("SELECT session_id FROM qa_history LIMIT 0;")
        except sqlite3.OperationalError:
            logger.info("迁移：为 qa_history 表添加 session_id 列")
            c.execute("ALTER TABLE qa_history ADD COLUMN session_id TEXT;")

        # —— qa_sessions 表：会话元信息（id/title/创建时间/更新时间）——
        c.execute(
            """
            CREATE TABLE IF NOT EXISTS qa_sessions (
                session_id TEXT PRIMARY KEY,
                title TEXT,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL,
                msg_count INTEGER DEFAULT 0
            );
            """
        )
        c.execute("CREATE INDEX IF NOT EXISTS idx_qa_sessions_updated ON qa_sessions(updated_at DESC);")

        # —— 每日归纳表：scheduler 每日生成的笔记归纳 ——
        c.execute(
            """
            CREATE TABLE IF NOT EXISTS daily_summaries (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                date TEXT NOT NULL UNIQUE,
                content TEXT NOT NULL,
                note_ids TEXT,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL
            );
            """
        )

        # —— 知识卡片表：每次 QA 后沉淀的结构化知识卡 ——
        # 一个卡片对应一次问答，记录核心总结/关键结论/落地场景/Agent 提问/用户回答/AI 补充
        c.execute(
            """
            CREATE TABLE IF NOT EXISTS knowledge_cards (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                qa_id INTEGER,
                session_id TEXT,
                title TEXT NOT NULL,
                core_summary TEXT NOT NULL,
                key_conclusion TEXT NOT NULL,
                application_scenario TEXT,
                agent_question TEXT,
                user_answer TEXT,
                ai_supplement TEXT,
                source_note_ids TEXT,
                status TEXT DEFAULT 'finalized',
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL,
                FOREIGN KEY (qa_id) REFERENCES qa_history(id)
            );
            """
        )
        c.execute("CREATE INDEX IF NOT EXISTS idx_cards_session ON knowledge_cards(session_id);")
        c.execute("CREATE INDEX IF NOT EXISTS idx_cards_created ON knowledge_cards(created_at DESC);")

        # —— 卡片-笔记 / 卡片-卡片 链接表 ——
        # source_type: 'card' | 'note'
        # target_type: 'card' | 'note'
        # 与现有 links 表（note-note）解耦，避免侵入原图谱计算
        c.execute(
            """
            CREATE TABLE IF NOT EXISTS card_links (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                source_type TEXT NOT NULL,
                source_id INTEGER NOT NULL,
                target_type TEXT NOT NULL,
                target_id INTEGER NOT NULL,
                weight REAL DEFAULT 1.0,
                reason TEXT,
                created_at TEXT NOT NULL,
                UNIQUE(source_type, source_id, target_type, target_id)
            );
            """
        )
        c.execute("CREATE INDEX IF NOT EXISTS idx_card_links_source ON card_links(source_type, source_id);")
        c.execute("CREATE INDEX IF NOT EXISTS idx_card_links_target ON card_links(target_type, target_id);")


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


def update_note_fields(
    note_id: int,
    *,
    title: Optional[str] = None,
    ocr_text: Optional[str] = None,
    summary: Optional[str] = None,
    keywords: Optional[List[str]] = None,
    embedding: Optional[Sequence[float]] = None,
    manually_edited: Optional[bool] = None,
) -> None:
    """人工编辑笔记字段（部分更新）。

    只更新传入的字段；manually_edited=True 表示人工编辑过，
    后续重新 OCR 时应保留人工修改（不覆盖）。
    """
    sets: List[str] = []
    params: List[Any] = []
    if title is not None:
        sets.append("title = ?")
        params.append(title)
    if ocr_text is not None:
        sets.append("ocr_text = ?")
        params.append(ocr_text)
    if summary is not None:
        sets.append("summary = ?")
        params.append(summary)
    if keywords is not None:
        sets.append("keywords = ?")
        params.append(json.dumps(keywords, ensure_ascii=False))
    if embedding is not None:
        sets.append("embedding = ?")
        params.append(json.dumps(list(embedding)))
    if manually_edited is not None:
        sets.append("manually_edited = ?")
        params.append(1 if manually_edited else 0)
    if not sets:
        return
    sets.append("processed_at = ?")
    params.append(_now())
    params.append(note_id)
    with _db_lock, get_conn() as conn:
        conn.execute(f"UPDATE notes SET {', '.join(sets)} WHERE id = ?;", params)


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


def delete_note(note_id: int) -> bool:
    """级联删除一条笔记：notes 行 + links + 缩略图文件。

    qa_history 中引用该笔记的记录不删（保留历史问答），但 citations 字段
    里的 note_id 会失效（前端展示时按 note_id 跳转会 404，可接受）。
    user_memory 中 related_qa_id 也不动。

    Returns: True 如果笔记存在且被删除。
    """
    note = get_note(note_id)
    if not note:
        return False
    with _db_lock, get_conn() as conn:
        # 1. 删 links
        conn.execute(
            "DELETE FROM links WHERE source_note_id = ? OR target_note_id = ?;",
            (note_id, note_id),
        )
        # 2. 删 notes 行
        conn.execute("DELETE FROM notes WHERE id = ?;", (note_id,))
    # 3. 删缩略图文件（在锁外做 IO）
    try:
        thumb_dir = Path(get_config().THUMBNAIL_DIR)
        for thumb in thumb_dir.glob(f"{note_id}.*"):
            try:
                thumb.unlink()
            except Exception:
                pass
    except Exception:
        pass
    return True


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
def insert_qa(*, question: str, answer: str, citations: List[Dict[str, Any]],
              session_id: Optional[str] = None) -> int:
    """记录一次问答，返回 qa_history.id。

    若提供 session_id，同步 upsert qa_sessions 表（更新 msg_count/updated_at，
    若是首条消息则用问题前 20 字符作为默认标题）。
    """
    now = _now()
    with _db_lock, get_conn() as conn:
        cur = conn.cursor()
        cur.execute(
            """
            INSERT INTO qa_history (question, answer, citations, created_at, session_id)
            VALUES (?, ?, ?, ?, ?);
            """,
            (question, answer, json.dumps(citations, ensure_ascii=False), now, session_id),
        )
        qa_id = int(cur.lastrowid)

        # 同步 upsert qa_sessions
        if session_id:
            existing = conn.execute(
                "SELECT session_id, title, msg_count FROM qa_sessions WHERE session_id = ?;",
                (session_id,),
            ).fetchone()
            if existing:
                # 已存在：更新 updated_at 和 msg_count
                new_count = int(existing["msg_count"] or 0) + 1
                cur.execute(
                    "UPDATE qa_sessions SET updated_at = ?, msg_count = ? WHERE session_id = ?;",
                    (now, new_count, session_id),
                )
            else:
                # 新会话：用问题前 20 字符作为默认标题
                default_title = question.strip()[:20] or "(新会话)"
                cur.execute(
                    """
                    INSERT INTO qa_sessions (session_id, title, created_at, updated_at, msg_count)
                    VALUES (?, ?, ?, ?, 1);
                    """,
                    (session_id, default_title, now, now),
                )
        return qa_id


def get_qa_history(limit: int = 50, offset: int = 0,
                   session_id: Optional[str] = None) -> List[Dict[str, Any]]:
    """返回问答历史。可按 session_id 过滤（同 session 的消息按时间正序）。"""
    with get_conn() as conn:
        if session_id:
            rows = conn.execute(
                "SELECT * FROM qa_history WHERE session_id = ? ORDER BY created_at ASC LIMIT ? OFFSET ?;",
                (session_id, int(limit), int(offset)),
            ).fetchall()
        else:
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


# ---------------------------------------------------------------------------
# qa_sessions CRUD
# ---------------------------------------------------------------------------
def list_qa_sessions(limit: int = 50) -> List[Dict[str, Any]]:
    """列出所有会话，按 updated_at 倒序。"""
    with get_conn() as conn:
        rows = conn.execute(
            """
            SELECT s.*,
                   (SELECT question FROM qa_history
                    WHERE session_id = s.session_id
                    ORDER BY created_at DESC LIMIT 1) AS last_question,
                   (SELECT answer FROM qa_history
                    WHERE session_id = s.session_id
                    ORDER BY created_at DESC LIMIT 1) AS last_answer
            FROM qa_sessions s
            ORDER BY s.updated_at DESC
            LIMIT ?;
            """,
            (int(limit),),
        ).fetchall()
        return [dict(r) for r in rows]


def get_qa_session(session_id: str) -> Optional[Dict[str, Any]]:
    """获取单个会话元信息。"""
    with get_conn() as conn:
        row = conn.execute(
            "SELECT * FROM qa_sessions WHERE session_id = ?;",
            (session_id,),
        ).fetchone()
        return dict(row) if row else None


def rename_qa_session(session_id: str, title: str) -> bool:
    """重命名会话标题。返回是否成功（会话存在则 True）。"""
    with _db_lock, get_conn() as conn:
        cur = conn.cursor()
        cur.execute(
            "UPDATE qa_sessions SET title = ?, updated_at = ? WHERE session_id = ?;",
            (title.strip()[:60], _now(), session_id),
        )
        return cur.rowcount > 0


def delete_qa_session(session_id: str) -> bool:
    """删除会话及其所有问答记录。返回是否成功。"""
    with _db_lock, get_conn() as conn:
        cur = conn.cursor()
        # 先删 qa_history 里该 session 的所有记录
        cur.execute("DELETE FROM qa_history WHERE session_id = ?;", (session_id,))
        # 再删 session 元信息
        cur.execute("DELETE FROM qa_sessions WHERE session_id = ?;", (session_id,))
        return cur.rowcount > 0


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


def list_feedback(limit: int = 100, offset: int = 0) -> List[Dict[str, Any]]:
    """返回反馈列表（用于学习用户偏好）。"""
    with get_conn() as conn:
        rows = conn.execute(
            "SELECT * FROM feedback ORDER BY created_at DESC LIMIT ? OFFSET ?;",
            (int(limit), int(offset)),
        ).fetchall()
        return [dict(r) for r in rows]


# ---------------------------------------------------------------------------
# user_memory CRUD（长期记忆）
# ---------------------------------------------------------------------------
def insert_memory(
    *,
    type: str,
    content: str,
    source: Optional[str] = None,
    weight: float = 0.5,
    embedding: Optional[Sequence[float]] = None,
    related_qa_id: Optional[int] = None,
) -> int:
    """新增一条长期记忆。type ∈ {preference, fact, correction, term}。"""
    with _db_lock, get_conn() as conn:
        cur = conn.cursor()
        cur.execute(
            """
            INSERT INTO user_memory (type, content, source, weight, embedding, related_qa_id, created_at)
            VALUES (?, ?, ?, ?, ?, ?, ?);
            """,
            (
                type,
                content,
                source,
                float(weight),
                json.dumps(list(embedding)) if embedding else None,
                related_qa_id,
                _now(),
            ),
        )
        return int(cur.lastrowid)


def list_memory(
    *,
    type: Optional[str] = None,
    limit: int = 100,
    offset: int = 0,
) -> List[Dict[str, Any]]:
    """列出长期记忆（可按 type 过滤）。按权重降序 + 创建时间降序。"""
    where = " WHERE type = ?" if type else ""
    params: List[Any] = [type] if type else []
    sql = (
        f"SELECT * FROM user_memory{where}"
        " ORDER BY weight DESC, created_at DESC LIMIT ? OFFSET ?;"
    )
    params.extend([int(limit), int(offset)])
    with get_conn() as conn:
        rows = conn.execute(sql, params).fetchall()
        out = []
        for r in rows:
            d = dict(r)
            if isinstance(d.get("embedding"), str):
                try:
                    d["embedding"] = json.loads(d["embedding"])
                except (json.JSONDecodeError, TypeError):
                    d["embedding"] = None
            out.append(d)
        return out


def get_memory(memory_id: int) -> Optional[Dict[str, Any]]:
    """按 id 获取单条记忆。"""
    with get_conn() as conn:
        row = conn.execute("SELECT * FROM user_memory WHERE id = ?;", (memory_id,)).fetchone()
        if row is None:
            return None
        d = dict(row)
        if isinstance(d.get("embedding"), str):
            try:
                d["embedding"] = json.loads(d["embedding"])
            except (json.JSONDecodeError, TypeError):
                d["embedding"] = None
        return d


def update_memory(
    memory_id: int,
    *,
    content: Optional[str] = None,
    weight: Optional[float] = None,
    type: Optional[str] = None,
) -> None:
    """更新记忆字段。"""
    sets: List[str] = []
    params: List[Any] = []
    if content is not None:
        sets.append("content = ?")
        params.append(content)
    if weight is not None:
        sets.append("weight = ?")
        params.append(float(weight))
    if type is not None:
        sets.append("type = ?")
        params.append(type)
    if not sets:
        return
    params.append(memory_id)
    with _db_lock, get_conn() as conn:
        conn.execute(f"UPDATE user_memory SET {', '.join(sets)} WHERE id = ?;", params)


def delete_memory(memory_id: int) -> bool:
    """删除一条记忆。返回是否删除成功。"""
    with _db_lock, get_conn() as conn:
        cur = conn.cursor()
        cur.execute("DELETE FROM user_memory WHERE id = ?;", (memory_id,))
        return cur.rowcount > 0


def search_similar_memory(query_vec: Sequence[float], top_k: int = 5) -> List[Dict[str, Any]]:
    """在全库记忆中扫描，返回与查询向量最相似的 top_k 记忆（带 score）。"""
    with get_conn() as conn:
        rows = conn.execute(
            "SELECT * FROM user_memory WHERE embedding IS NOT NULL ORDER BY weight DESC, created_at DESC LIMIT 500;"
        ).fetchall()
    scored: List[Tuple[float, Dict[str, Any]]] = []
    for r in rows:
        d = dict(r)
        emb = None
        if isinstance(d.get("embedding"), str):
            try:
                emb = json.loads(d["embedding"])
            except (json.JSONDecodeError, TypeError):
                emb = None
        if not emb:
            continue
        score = cosine_similarity(query_vec, emb)
        # 用权重做轻微加权（weight 0.5 → 不变；weight 1.0 → ×1.1；weight 0.0 → ×0.9）
        weighted = score * (0.9 + 0.2 * float(d.get("weight", 0.5)))
        scored.append((weighted, d))
    scored.sort(key=lambda x: x[0], reverse=True)
    return [{"score": round(s, 4), "memory": d} for s, d in scored[: int(top_k)]]


def touch_memory(memory_id: int) -> None:
    """记忆被引用时更新 use_count 和 last_used_at。"""
    with _db_lock, get_conn() as conn:
        conn.execute(
            """
            UPDATE user_memory
            SET use_count = use_count + 1, last_used_at = ?
            WHERE id = ?;
            """,
            (_now(), memory_id),
        )


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


# ---------------------------------------------------------------------------
# 崩溃恢复 + OCR 重试 + 每日归纳 + 记忆衰减
# ---------------------------------------------------------------------------
def reset_stale_processing_notes() -> int:
    """启动时把 status='processing' 的笔记重置为 pending（崩溃恢复）。

    返回重置的条数。
    """
    with _db_lock, get_conn() as conn:
        cur = conn.cursor()
        cur.execute(
            "UPDATE notes SET status='pending' WHERE status='processing';"
        )
        return cur.rowcount


def list_notes_by_date(date_str: str) -> List[Dict[str, Any]]:
    """列出某天（本地日期，格式 YYYY-MM-DD）创建的 done 笔记。"""
    with get_conn() as conn:
        rows = conn.execute(
            "SELECT * FROM notes WHERE status='done' "
            "AND substr(created_at, 1, 10) = ? "
            "ORDER BY created_at ASC;",
            (date_str,),
        ).fetchall()
        return [dict(r) for r in rows]


def increment_retry_count(note_id: int, error: str) -> int:
    """递增重试次数并记录 last_error，返回新的重试次数。"""
    with _db_lock, get_conn() as conn:
        cur = conn.cursor()
        cur.execute(
            "UPDATE notes SET retry_count = retry_count + 1, last_error = ? WHERE id = ?;",
            (error[:500], note_id),
        )
        row = conn.execute(
            "SELECT retry_count FROM notes WHERE id = ?;", (note_id,)
        ).fetchone()
        return int(row["retry_count"]) if row else 0


def list_failed_notes_for_retry(max_retries: int = 3, limit: int = 50) -> List[Dict[str, Any]]:
    """列出可重试的失败笔记（retry_count < max_retries）。"""
    with get_conn() as conn:
        rows = conn.execute(
            "SELECT * FROM notes WHERE status='failed' AND retry_count < ? "
            "ORDER BY created_at ASC LIMIT ?;",
            (int(max_retries), int(limit)),
        ).fetchall()
        return [dict(r) for r in rows]


def decay_link_weights(decay_factor: float = 0.95, min_weight: float = 0.1) -> Dict[str, int]:
    """对所有 links.weight 做指数衰减（记忆衰减）。

    weight *= decay_factor；权重低于 min_weight 的删除。
    返回 {"decayed": N, "removed": M}。
    """
    with _db_lock, get_conn() as conn:
        cur = conn.cursor()
        # 衰减
        cur.execute(
            "UPDATE links SET weight = weight * ? WHERE weight >= ?;",
            (float(decay_factor), float(min_weight)),
        )
        decayed = cur.rowcount
        # 删除低于阈值的
        cur.execute("DELETE FROM links WHERE weight < ?;", (float(min_weight),))
        removed = cur.rowcount
        return {"decayed": decayed, "removed": removed}


def decay_memory_weights(decay_factor: float = 0.98, min_weight: float = 0.2) -> Dict[str, int]:
    """对 user_memory.weight 做衰减。

    被使用过的记忆（use_count > 0）衰减更慢（× decay_factor^0.5），
    未使用过的正常衰减（× decay_factor）。
    低于 min_weight 的删除（除了 ocr_correction / ocr_addition，这些是用户明确修正，
    即使不常用也不该忘）。
    """
    with _db_lock, get_conn() as conn:
        cur = conn.cursor()
        # 使用过的：慢衰减
        cur.execute(
            "UPDATE user_memory SET weight = weight * ? "
            "WHERE use_count > 0 AND weight >= ?;",
            (float(decay_factor ** 0.5), float(min_weight)),
        )
        # 未使用过的：正常衰减
        cur.execute(
            "UPDATE user_memory SET weight = weight * ? "
            "WHERE use_count = 0 AND weight >= ?;",
            (float(decay_factor), float(min_weight)),
        )
        # 删除低于阈值的（保留用户明确修正的记忆）
        cur.execute(
            "DELETE FROM user_memory WHERE weight < ? "
            "AND type NOT IN ('ocr_correction', 'ocr_addition', 'correction');",
            (float(min_weight),),
        )
        removed = cur.rowcount
        return {"removed": removed}


def upsert_daily_summary(date_str: str, content: str, note_ids: List[int]) -> int:
    """写入或更新某天的归纳。返回 id。"""
    now = _now()
    with _db_lock, get_conn() as conn:
        cur = conn.cursor()
        cur.execute(
            """
            INSERT INTO daily_summaries (date, content, note_ids, created_at, updated_at)
            VALUES (?, ?, ?, ?, ?)
            ON CONFLICT(date) DO UPDATE SET
                content = excluded.content,
                note_ids = excluded.note_ids,
                updated_at = excluded.updated_at;
            """,
            (date_str, content, json.dumps(note_ids), now, now),
        )
        row = conn.execute(
            "SELECT id FROM daily_summaries WHERE date = ?;", (date_str,)
        ).fetchone()
        return int(row["id"]) if row else 0


def get_daily_summary(date_str: str) -> Optional[Dict[str, Any]]:
    """获取某天的归纳。"""
    with get_conn() as conn:
        row = conn.execute(
            "SELECT * FROM daily_summaries WHERE date = ?;", (date_str,)
        ).fetchone()
        if not row:
            return None
        d = dict(row)
        if isinstance(d.get("note_ids"), str):
            try:
                d["note_ids"] = json.loads(d["note_ids"])
            except (json.JSONDecodeError, TypeError):
                d["note_ids"] = []
        return d


def list_recent_daily_summaries(limit: int = 7) -> List[Dict[str, Any]]:
    """列出最近 N 天的归纳。"""
    with get_conn() as conn:
        rows = conn.execute(
            "SELECT * FROM daily_summaries ORDER BY date DESC LIMIT ?;",
            (int(limit),),
        ).fetchall()
        out = []
        for r in rows:
            d = dict(r)
            if isinstance(d.get("note_ids"), str):
                try:
                    d["note_ids"] = json.loads(d["note_ids"])
                except (json.JSONDecodeError, TypeError):
                    d["note_ids"] = []
            out.append(d)
        return out


# ---------------------------------------------------------------------------
# 知识卡片 CRUD
# ---------------------------------------------------------------------------
def insert_knowledge_card(
    *,
    qa_id: Optional[int],
    session_id: Optional[str],
    title: str,
    core_summary: str,
    key_conclusion: str,
    application_scenario: str = "",
    agent_question: str = "",
    user_answer: str = "",
    ai_supplement: str = "",
    source_note_ids: List[int],
    status: str = "draft",
) -> Optional[int]:
    """插入一条知识卡片，返回 id。"""
    with _db_lock, get_conn() as conn:
        cur = conn.cursor()
        now = _now()
        cur.execute(
            """
            INSERT INTO knowledge_cards
                (qa_id, session_id, title, core_summary, key_conclusion,
                 application_scenario, agent_question, user_answer, ai_supplement,
                 source_note_ids, status, created_at, updated_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?);
            """,
            (
                qa_id, session_id, title.strip(), core_summary.strip(),
                key_conclusion.strip(), application_scenario.strip(),
                agent_question.strip(), user_answer.strip(), ai_supplement.strip(),
                json.dumps(source_note_ids), status, now, now,
            ),
        )
        return cur.lastrowid


def update_knowledge_card(card_id: int, **fields) -> bool:
    """更新卡片字段。支持 user_answer/ai_supplement/status/title 等。"""
    if not fields:
        return False
    allowed = {
        "title", "core_summary", "key_conclusion", "application_scenario",
        "agent_question", "user_answer", "ai_supplement", "source_note_ids",
        "status",
    }
    sets = []
    vals: List[Any] = []
    for k, v in fields.items():
        if k not in allowed:
            continue
        if k == "source_note_ids" and isinstance(v, list):
            v = json.dumps(v)
        sets.append(f"{k} = ?")
        vals.append(v)
    if not sets:
        return False
    sets.append("updated_at = ?")
    vals.append(_now())
    vals.append(card_id)
    with _db_lock, get_conn() as conn:
        cur = conn.cursor()
        cur.execute(
            f"UPDATE knowledge_cards SET {', '.join(sets)} WHERE id = ?;",
            vals,
        )
        return cur.rowcount > 0


def get_knowledge_card(card_id: int) -> Optional[Dict[str, Any]]:
    """按 id 取卡片详情。"""
    with get_conn() as conn:
        row = conn.execute(
            "SELECT * FROM knowledge_cards WHERE id = ?;", (card_id,)
        ).fetchone()
    if not row:
        return None
    d = dict(row)
    if isinstance(d.get("source_note_ids"), str):
        try:
            d["source_note_ids"] = json.loads(d["source_note_ids"])
        except (json.JSONDecodeError, TypeError):
            d["source_note_ids"] = []
    return d


def list_knowledge_cards(
    limit: int = 50, offset: int = 0, session_id: Optional[str] = None
) -> Dict[str, Any]:
    """列出卡片，返回 {items, total}。"""
    with get_conn() as conn:
        if session_id:
            total = conn.execute(
                "SELECT COUNT(*) AS n FROM knowledge_cards WHERE session_id = ?;",
                (session_id,),
            ).fetchone()["n"]
            rows = conn.execute(
                "SELECT * FROM knowledge_cards WHERE session_id = ? "
                "ORDER BY created_at DESC LIMIT ? OFFSET ?;",
                (session_id, int(limit), int(offset)),
            ).fetchall()
        else:
            total = conn.execute(
                "SELECT COUNT(*) AS n FROM knowledge_cards;"
            ).fetchone()["n"]
            rows = conn.execute(
                "SELECT * FROM knowledge_cards ORDER BY created_at DESC LIMIT ? OFFSET ?;",
                (int(limit), int(offset)),
            ).fetchall()
    items = []
    for r in rows:
        d = dict(r)
        if isinstance(d.get("source_note_ids"), str):
            try:
                d["source_note_ids"] = json.loads(d["source_note_ids"])
            except (json.JSONDecodeError, TypeError):
                d["source_note_ids"] = []
        items.append(d)
    return {"items": items, "total": total, "limit": limit, "offset": offset}


def delete_knowledge_card(card_id: int) -> bool:
    """删除卡片，同时级联清理 card_links。"""
    with _db_lock, get_conn() as conn:
        cur = conn.cursor()
        # 先删链接
        cur.execute(
            "DELETE FROM card_links WHERE "
            "(source_type='card' AND source_id=?) OR "
            "(target_type='card' AND target_id=?);",
            (card_id, card_id),
        )
        cur.execute("DELETE FROM knowledge_cards WHERE id = ?;", (card_id,))
        return cur.rowcount > 0


# ---------------------------------------------------------------------------
# 卡片链接 CRUD（card-note / card-card）
# ---------------------------------------------------------------------------
def insert_card_link(
    *,
    source_type: str,
    source_id: int,
    target_type: str,
    target_id: int,
    weight: float = 1.0,
    reason: str = "",
) -> bool:
    """插入一条 card_links，已存在则忽略。"""
    with _db_lock, get_conn() as conn:
        cur = conn.cursor()
        cur.execute(
            """
            INSERT OR IGNORE INTO card_links
                (source_type, source_id, target_type, target_id, weight, reason, created_at)
            VALUES (?, ?, ?, ?, ?, ?, ?);
            """,
            (source_type, source_id, target_type, target_id, float(weight),
             reason.strip(), _now()),
        )
        return cur.rowcount > 0


def get_card_links_for(card_id: int) -> List[Dict[str, Any]]:
    """取一个卡片的所有链接（出边 + 入边）。"""
    with get_conn() as conn:
        rows = conn.execute(
            "SELECT * FROM card_links WHERE "
            "(source_type='card' AND source_id=?) OR "
            "(target_type='card' AND target_id=?);",
            (card_id, card_id),
        ).fetchall()
    return [dict(r) for r in rows]


def get_all_card_links() -> List[Dict[str, Any]]:
    """取全部 card_links（图谱用）。"""
    with get_conn() as conn:
        rows = conn.execute(
            "SELECT * FROM card_links ORDER BY weight DESC;"
        ).fetchall()
    return [dict(r) for r in rows]


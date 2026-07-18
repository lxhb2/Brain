"""图谱构建与查询 API。

包含：
- recompute_links_for_note(note_id): 重新计算某笔记与全库其他 done 笔记的候选链接
- get_graph(filters): 返回节点与边用于前端可视化
- get_neighbors(note_id): 邻居查询
- apply_feedback(qa_id, rating): 根据用户反馈调整链接权重
"""
from __future__ import annotations

import math
from datetime import datetime
from typing import Any, Dict, List, Optional, Sequence

import database
from config import get_config


def _parse_dt(ts: Optional[str]) -> Optional[datetime]:
    """把 ISO 字符串解析为 datetime（含时区），失败返回 None。"""
    if not ts:
        return None
    try:
        return datetime.fromisoformat(ts.replace("Z", "+00:00"))
    except (ValueError, TypeError):
        return None


def _jaccard(a: Sequence[str], b: Sequence[str]) -> float:
    """两个关键词集合的 Jaccard 相似度。"""
    sa = {x.lower() for x in a if x}
    sb = {y.lower() for y in b if y}
    if not sa or not sb:
        return 0.0
    inter = sa & sb
    union = sa | sb
    return len(inter) / len(union) if union else 0.0


def _temporal_decay(days_delta: float) -> float:
    """时间衰减：exp(-|Δt|/30)。"""
    try:
        return math.exp(-abs(float(days_delta)) / 30.0)
    except (TypeError, ValueError):
        return 0.0


def _compose_link_type(sim: float, jac: float, decay: float) -> str:
    """根据三个分量主导来源决定链接类型。"""
    contrib = {"semantic": sim, "keyword": jac, "temporal": decay}
    return max(contrib, key=contrib.get)


def recompute_links_for_note(note_id: int) -> int:
    """重算某条笔记与全库其他 done 笔记的候选链接。

    流程：
      1. 删除该笔记参与的旧链接
      2. 取本笔记 embedding/keywords/created_at
      3. 与其他每条 done 笔记计算 weight = α·cos + β·jaccard + γ·decay
      4. weight > 阈值则入库

    返回新增/更新的链接数。
    """
    cfg = get_config()
    target = database.get_note(note_id)
    if not target or target.get("status") != "done":
        return 0

    target_emb = target.get("embedding") or []
    target_kw = target.get("keywords") or []
    target_t = _parse_dt(target.get("created_at"))

    # 清旧
    database.delete_links_for_note(note_id)

    others = [n for n in database.get_done_notes_with_embeddings() if n["id"] != note_id]
    count = 0
    for other in others:
        sim = database.cosine_similarity(target_emb, other.get("embedding") or [])
        jac = _jaccard(target_kw, other.get("keywords") or [])

        other_t = _parse_dt(other.get("created_at"))
        if target_t and other_t:
            delta_days = (target_t - other_t).total_seconds() / 86400.0
            decay = _temporal_decay(delta_days)
        else:
            decay = 0.0

        weight = cfg.LINK_ALPHA * sim + cfg.LINK_BETA * jac + cfg.LINK_GAMMA * decay
        if weight <= cfg.LINK_WEIGHT_THRESHOLD:
            continue

        link_type = _compose_link_type(
            cfg.LINK_ALPHA * sim,
            cfg.LINK_BETA * jac,
            cfg.LINK_GAMMA * decay,
        )
        parts: List[str] = []
        if sim > 0:
            parts.append(f"语义相似度 {sim:.2f}")
        if jac > 0:
            parts.append(f"关键词重合 {jac:.2f}")
        if decay > 0:
            parts.append(f"时间邻近 {decay:.2f}")
        reason = "；".join(parts) if parts else "综合关联"

        a, b = (note_id, other["id"]) if note_id < other["id"] else (other["id"], note_id)
        database.insert_link(
            source_note_id=a,
            target_note_id=b,
            weight=float(weight),
            link_type=link_type,
            reason=reason,
        )
        count += 1
    return count


def get_graph(filters: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    """返回图谱的节点与边，支持按 device/app/status 筛选节点。

    filters 可包含：device, app, status, q（标题/摘要模糊匹配）。
    """
    filters = filters or {}
    notes = database.list_notes(
        device=filters.get("device"),
        app=filters.get("app"),
        q=filters.get("q"),
        status=filters.get("status"),
        limit=100000,
        offset=0,
    )
    visible_ids = {n["id"] for n in notes}
    nodes = [
        {
            "id": n["id"],
            "title": n.get("title") or "(未命名)",
            "source_device": n.get("source_device"),
            "source_app": n.get("source_app"),
            "thumbnail_path": n.get("thumbnail_path"),
            "status": n.get("status"),
            "created_at": n.get("created_at"),
        }
        for n in notes
    ]
    edges = []
    for e in database.list_links():
        if e["source_note_id"] in visible_ids and e["target_note_id"] in visible_ids:
            edges.append({
                "source": e["source_note_id"],
                "target": e["target_note_id"],
                "weight": e["weight"],
                "link_type": e.get("link_type"),
                "reason": e.get("reason"),
            })
    return {"nodes": nodes, "edges": edges}


def get_neighbors(note_id: int) -> Dict[str, Any]:
    """返回某节点的邻居节点与边。"""
    pairs = database.get_neighbors(note_id)
    nodes_map: Dict[int, Dict[str, Any]] = {}
    edges = []
    for item in pairs:
        node = item["node"]
        e = item["edge"]
        if node and node["id"] != note_id:
            nodes_map[node["id"]] = {
                "id": node["id"],
                "title": node.get("title") or "(未命名)",
                "source_device": node.get("source_device"),
                "source_app": node.get("source_app"),
                "thumbnail_path": node.get("thumbnail_path"),
                "status": node.get("status"),
                "created_at": node.get("created_at"),
            }
        edges.append({
            "source": e["source_note_id"],
            "target": e["target_note_id"],
            "weight": e["weight"],
            "link_type": e.get("link_type"),
            "reason": e.get("reason"),
        })
    # 去重边
    seen = set()
    unique_edges = []
    for e in edges:
        key = (e["source"], e["target"], e.get("link_type"))
        if key in seen:
            continue
        seen.add(key)
        unique_edges.append(e)
    return {"nodes": list(nodes_map.values()), "edges": unique_edges}


def apply_feedback(qa_id: int, rating: str) -> None:
    """根据用户反馈调整链接权重。

    - 'up': 对问答引用的笔记两两之间的链接权重 +0.05
    - 'down': 对引用笔记两两之间的链接权重 -0.10

    所有权重 clamp 到 [0, 1]。
    """
    qa = database.get_qa(qa_id)
    if not qa:
        return
    citations = qa.get("citations") or []
    note_ids = [c.get("note_id") for c in citations if c.get("note_id") is not None]
    if len(note_ids) < 2:
        return
    delta = 0.05 if rating == "up" else -0.10
    # 对每对引用笔记调整其间的所有链接
    for i in range(len(note_ids)):
        for j in range(i + 1, len(note_ids)):
            a, b = note_ids[i], note_ids[j]
            database.adjust_link_weight(a, b, delta)

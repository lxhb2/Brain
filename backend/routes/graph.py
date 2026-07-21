"""图谱相关 API 路由。"""
from __future__ import annotations

from typing import Optional

from fastapi import APIRouter, Query

import database
import graph_api

router = APIRouter(prefix="/api/graph", tags=["graph"])


@router.get("")
def get_graph(
    device: Optional[str] = Query(None),
    app: Optional[str] = Query(None),
    q: Optional[str] = Query(None),
    status: Optional[str] = Query(None),
):
    """返回图谱节点与边，支持筛选。"""
    filters = {"device": device, "app": app, "q": q, "status": status}
    # 过滤掉 None 值
    filters = {k: v for k, v in filters.items() if v is not None}
    return graph_api.get_graph(filters)


@router.get("/neighbors/{note_id}")
def get_neighbors(note_id: int):
    """返回某节点的邻居节点与边。"""
    return graph_api.get_neighbors(note_id)


@router.get("/cards")
def get_graph_with_cards(
    center_card_id: Optional[int] = Query(None, description="以某卡片为中心，返回该卡片及其引用的笔记 + 邻近卡片"),
):
    """返回包含知识卡片的混合图谱。

    返回结构：
    {
      "nodes": [{id, type:'note'|'card', title, ...}],
      "edges": [{source, target, source_type, target_type, weight, reason}]
    }

    - 不传 center_card_id：返回所有卡片 + 所有笔记 + note-note 链接 + card-note 链接
    - 传 center_card_id：只返回该卡片 + 其引用的笔记 + 这些笔记的相关笔记（1 跳）
    """
    nodes = []
    edges = []

    if center_card_id is not None:
        # 单卡片中心模式
        center = database.get_knowledge_card(center_card_id)
        if not center:
            return {"nodes": [], "edges": []}
        # 卡片节点
        nodes.append({
            "id": f"card:{center['id']}",
            "type": "card",
            "ref_id": center["id"],
            "title": center["title"],
            "subtitle": center.get("core_summary", "")[:80],
            "created_at": center.get("created_at"),
        })
        # 引用的笔记
        note_ids = center.get("source_note_ids", []) or []
        for nid in note_ids:
            note = database.get_note(int(nid))
            if note:
                nodes.append({
                    "id": f"note:{note['id']}",
                    "type": "note",
                    "ref_id": note["id"],
                    "title": note.get("title") or f"笔记 #{note['id']}",
                    "subtitle": note.get("summary", "")[:80] if note.get("summary") else None,
                    "status": note.get("status"),
                    "thumbnail_path": note.get("thumbnail_path"),
                    "created_at": note.get("created_at"),
                })
                edges.append({
                    "source": f"card:{center['id']}",
                    "target": f"note:{note['id']}",
                    "source_type": "card",
                    "target_type": "note",
                    "weight": 1.0,
                    "reason": "卡片引用",
                })
        # 这些笔记之间的链接（1 跳邻居）
        if note_ids:
            all_links = database.list_links()
            note_id_set = set(int(nid) for nid in note_ids)
            for link in all_links:
                s = int(link["source_note_id"])
                t = int(link["target_note_id"])
                if s in note_id_set and t in note_id_set:
                    edges.append({
                        "source": f"note:{s}",
                        "target": f"note:{t}",
                        "source_type": "note",
                        "target_type": "note",
                        "weight": float(link.get("weight", 1.0)),
                        "reason": link.get("reason") or "相似",
                    })
        return {"nodes": nodes, "edges": edges}

    # 全图模式：所有卡片 + 所有笔记 + 两类链接
    # 卡片节点
    cards_res = database.list_knowledge_cards(limit=500)
    for c in cards_res["items"]:
        nodes.append({
            "id": f"card:{c['id']}",
            "type": "card",
            "ref_id": c["id"],
            "title": c["title"],
            "subtitle": c.get("core_summary", "")[:80],
            "created_at": c.get("created_at"),
        })

    # 笔记节点
    notes_list = database.list_notes(limit=1000, status="done")
    for n in notes_list:
        nodes.append({
            "id": f"note:{n['id']}",
            "type": "note",
            "ref_id": n["id"],
            "title": n.get("title") or f"笔记 #{n['id']}",
            "subtitle": n.get("summary", "")[:80] if n.get("summary") else None,
            "status": n.get("status"),
            "thumbnail_path": n.get("thumbnail_path"),
            "created_at": n.get("created_at"),
        })

    # note-note 链接
    for link in database.list_links():
        edges.append({
            "source": f"note:{link['source_note_id']}",
            "target": f"note:{link['target_note_id']}",
            "source_type": "note",
            "target_type": "note",
            "weight": float(link.get("weight", 1.0)),
            "reason": link.get("reason") or "相似",
        })

    # card-note 链接
    for cl in database.get_all_card_links():
        s_type = cl["source_type"]
        t_type = cl["target_type"]
        s_id = cl["source_id"]
        t_id = cl["target_id"]
        edges.append({
            "source": f"{s_type}:{s_id}",
            "target": f"{t_type}:{t_id}",
            "source_type": s_type,
            "target_type": t_type,
            "weight": float(cl.get("weight", 1.0)),
            "reason": cl.get("reason") or "",
        })

    return {"nodes": nodes, "edges": edges}

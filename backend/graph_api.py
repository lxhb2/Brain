"""图谱构建与查询 API。

包含：
- recompute_links_for_note(note_id): 重新计算某笔记与全库其他 done 笔记的候选链接
- get_graph(filters): 返回节点与边用于前端可视化
- get_neighbors(note_id): 邻居查询
- apply_feedback(qa_id, rating): 根据用户反馈调整链接权重
"""
from __future__ import annotations

import re
from typing import Any, Dict, List, Optional, Sequence

import database
from config import get_config, get_link_params_runtime


def _jaccard(a: Sequence[str], b: Sequence[str]) -> float:
    """两个关键词集合的 Jaccard 相似度。"""
    sa = {x.lower() for x in a if x}
    sb = {y.lower() for y in b if y}
    if not sa or not sb:
        return 0.0
    inter = sa & sb
    union = sa | sb
    return len(inter) / len(union) if union else 0.0


_WORD_RE = re.compile(r"[a-z][a-z0-9]+", re.IGNORECASE)
_CJK_RE = re.compile(r"[\u4e00-\u9fff]+")
_CONTENT_STOP = {
    "可以", "使用", "内容", "总结", "笔记", "文档", "知识", "信息", "系统",
    "学习", "方法", "过程", "结果", "需要", "重要", "帮助", "工作", "记录",
    "的", "是", "在", "和", "与", "了", "我", "你", "他", "这", "那", "个",
    "一个", "一下", "一些", "一次", "一条", "一步", "自己", "他们", "我们",
    "你们", "什么", "怎么", "为什么", "因为", "所以", "如果", "但是", "可是",
    "然后", "另外", "其次", "其他", "其它", "还有", "以及", "并且", "不过",
    "只是", "就是", "也是", "都是", "或者", "而且", "不要", "不会", "不是",
    "没有", "可能", "应该", "必须", "关键", "基本", "一般", "常见", "简单",
    "例如", "比如", "问题", "部分", "步骤", "例子", "文章", "手册",
    "个人", "之前", "之后", "后来", "时候", "开始", "现在", "同时",
    "此外", "如何", "决定",
}
_CJK_STOP_CHARS = set("的了是在和与了我你这那个")


def _text_tokens(text: str) -> set[str]:
    """构造轻量内容词：英文单词 + 中文相邻二字组。"""
    tokens = {token.lower() for token in _WORD_RE.findall(text or "")}
    for segment in _CJK_RE.findall(text or ""):
        if len(segment) >= 2:
            tokens.update(segment[i : i + 2] for i in range(len(segment) - 1))
    return {
        token for token in tokens
        if token not in _CONTENT_STOP and not any(ch in _CJK_STOP_CHARS for ch in token)
    }


def _content_tokens(note: Dict[str, Any]) -> set[str]:
    """从标题、摘要、关键词和 OCR 前段中提取可比较的内容证据。"""
    tokens: set[str] = set()
    for keyword in note.get("keywords") or []:
        token = str(keyword).strip().lower()
        if (
            token
            and not token.isdigit()
            and (len(token) > 1 or any("\u4e00" <= ch <= "\u9fff" for ch in token))
            and not any(ch in _CJK_STOP_CHARS for ch in token)
        ):
            tokens.add(token)
    fields = (
        note.get("title"),
        note.get("summary"),
        note.get("condition_text"),
        note.get("action_text"),
        note.get("consequence_text"),
        (note.get("ocr_text") or "")[:2000],
    )
    tokens.update(_text_tokens(" ".join(str(value or "") for value in fields)))
    return tokens


def _content_overlap(a: set[str], b: set[str]) -> tuple[float, List[str]]:
    """返回内容词重合比例与少量共享证据，比例使用 Dice 防止长文稀释。"""
    shared = a & b
    if not a or not b or not shared:
        return 0.0, []
    ratio = 2.0 * len(shared) / (len(a) + len(b))
    examples = sorted(shared, key=lambda token: (len(token), token))[:4]
    return ratio, examples


def _compose_link_type(sim: float, jac: float, overlap: float) -> str:
    """根据内容证据的主导来源决定链接类型。"""
    contrib = {"semantic": sim, "keyword": max(jac, overlap)}
    return max(contrib, key=contrib.get)


def recompute_links_for_note(note_id: int) -> int:
    """重算某条笔记与全库其他 done 笔记的内容相关链接。

    参考 Obsidian：只有“强内容证据”才连边，不靠时间邻近或微弱相似度
    把图连成网。候选边必须通过语义/关键词/内容词门槛之一，然后只保留
    当前节点最相关的前 K 条。
    """
    cfg = get_config()
    params = get_link_params_runtime()
    target = database.get_note(note_id)
    if not target or target.get("status") != "done":
        return 0

    target_emb = target.get("embedding") or []
    target_kw = {str(x).strip().lower() for x in (target.get("keywords") or []) if str(x).strip()}
    target_content = _content_tokens(target)

    # 清旧
    database.delete_links_for_note(note_id)

    others = [n for n in database.get_done_notes_with_embeddings() if n["id"] != note_id]
    candidates: List[Dict[str, Any]] = []
    for other in others:
        sim = database.cosine_similarity(target_emb, other.get("embedding") or [])
        other_kw = {str(x).strip().lower() for x in (other.get("keywords") or []) if str(x).strip()}
        jac = _jaccard(target_kw, other_kw)
        overlap, shared_examples = _content_overlap(target_content, _content_tokens(other))
        shared_keywords = sorted(target_kw & other_kw)
        shared_terms = len(shared_keywords) + len(shared_examples)

        semantic_pass = sim >= cfg.LINK_SEMANTIC_GATE
        keyword_pass = jac >= cfg.LINK_KEYWORD_GATE and shared_terms >= cfg.LINK_MIN_SHARED_TERMS
        content_pass = overlap >= cfg.LINK_CONTENT_GATE and shared_terms >= cfg.LINK_MIN_SHARED_TERMS
        if not (semantic_pass or keyword_pass or content_pass):
            continue

        weight = params["alpha"] * sim + params["beta"] * jac + params["gamma"] * overlap
        if weight <= params["threshold"]:
            continue

        link_type = _compose_link_type(
            sim,
            jac,
            overlap,
        )
        parts: List[str] = []
        if sim > 0:
            parts.append(f"语义相似度 {sim:.2f}")
        if jac > 0:
            parts.append(f"关键词重合 {jac:.2f}")
        if shared_examples:
            parts.append("共享内容词 " + "、".join(shared_examples))
        if shared_keywords:
            parts.append("共享关键词 " + "、".join(shared_keywords[:4]))
        reason = "；".join(parts) if parts else "内容相关"

        candidates.append({
            "other_id": other["id"],
            "weight": max(0.0, min(1.0, float(weight))),
            "link_type": link_type,
            "reason": reason,
        })

    candidates.sort(key=lambda item: item["weight"], reverse=True)
    count = 0
    for item in candidates[: max(1, int(cfg.LINK_TOP_K))]:
        other_id = item.pop("other_id")
        a, b = (note_id, other_id) if note_id < other_id else (other_id, note_id)
        database.insert_link(
            source_note_id=a,
            target_note_id=b,
            weight=item["weight"],
            link_type=item["link_type"],
            reason=item["reason"],
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

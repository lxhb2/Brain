"""RAG 问答引擎（带长期记忆 + 自我成长）。

ask(question, session_id) 流程：
  1. 把问题向量化（无 key 时用 demo 随机向量）
  2. 检索相关长期记忆（user_memory 表），注入 prompt 上下文
  3. 检索最近 5 轮对话历史（同 session_id），注入 prompt 做多轮
  4. 在全库 done 笔记中向量检索 top 5
  5. 组装 RAG 上下文（记忆 + 历史 + 笔记）
  6. 调 chat completion，要求引用 note id
  7. 返回 {answer, citations, memories_used}
  8. 写入 qa_history（带 session_id）

自我成长：
  - 反馈 down + correction 时，extract_memory_from_correction 提取记忆点存入 user_memory
  - 反馈 up 时，提升相关记忆权重
  - 每次 ask 时如果命中记忆，touch_memory 更新使用次数
"""
from __future__ import annotations

import logging
import random
from typing import Any, Dict, List, Optional

import database
from config import get_config
from ocr_processor import _demo_embedding, _get_client, _embed_text

logger = logging.getLogger("brain.qa")

_SYSTEM_PROMPT = (
    "你是 Brain 笔记知识库的问答助手。请【仅】依据下方提供的笔记内容、"
    "用户长期记忆、对话历史回答用户问题。"
    "如果笔记中没有相关信息，请明确说明「当前知识库中未找到相关笔记」。"
    "回答时在句末用 [note_id] 形式引用来源笔记的 id，例如 [12]。"
    "保持回答简洁、准确，不要编造笔记中不存在的内容。"
    "如果用户长期记忆中有相关偏好或事实，请优先参考。"
)

# 多轮对话最多回溯几轮
_MAX_HISTORY_TURNS = 5
# 记忆检索 top k
_MAX_MEMORIES = 5


def _embed_question(question: str) -> List[float]:
    """把问题转成向量。无 key 时返回 demo 随机向量。"""
    client = _get_client()
    if client is None:
        return _demo_embedding()
    return _embed_text(client, question)


def _build_context(hits: List[Dict[str, Any]]) -> str:
    """把检索到的笔记组装成供 LLM 的上下文字符串。"""
    blocks: List[str] = []
    for i, h in enumerate(hits, start=1):
        n = h["note"]
        ocr = (n.get("ocr_text") or "").strip()
        if len(ocr) > 800:
            ocr = ocr[:800] + "..."
        summary = (n.get("summary") or "").strip()
        block = (
            f"--- 笔记 #{n['id']} ---\n"
            f"标题: {n.get('title') or '(未命名)'}\n"
            f"摘要: {summary}\n"
            f"OCR 内容:\n{ocr}\n"
        )
        blocks.append(block)
    return "\n".join(blocks)


def _build_memory_context(memories: List[Dict[str, Any]]) -> str:
    """把检索到的长期记忆组装成 prompt 片段。"""
    if not memories:
        return ""
    lines = ["=== 用户长期记忆（优先参考） ==="]
    for m in memories:
        d = m.get("memory", m)
        mtype = d.get("type", "")
        content = (d.get("content") or "").strip()
        label = {
            "preference": "用户偏好",
            "fact": "已知事实",
            "correction": "用户修正",
            "term": "常用术语",
        }.get(mtype, mtype)
        lines.append(f"[{label}] {content}")
    return "\n".join(lines) + "\n"


def _build_history_context(session_id: Optional[str], current_question: str) -> str:
    """把同 session 的最近几轮对话组装成上下文（用于多轮）。"""
    if not session_id:
        return ""
    try:
        history = database.get_qa_history(limit=_MAX_HISTORY_TURNS * 2, session_id=session_id)
    except Exception:
        return ""
    if not history:
        return ""
    # 倒序变正序
    history = list(reversed(history))
    lines = ["=== 对话历史 ==="]
    for h in history:
        q = (h.get("question") or "").strip()
        a = (h.get("answer") or "").strip()
        if a and len(a) > 200:
            a = a[:200] + "..."
        lines.append(f"用户: {q}")
        lines.append(f"助手: {a}")
    return "\n".join(lines) + "\n"


def _make_citations(hits: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """从检索结果生成引用列表（note_id/title/snippet）。"""
    out = []
    for h in hits:
        n = h["note"]
        snippet = (n.get("summary") or n.get("ocr_text") or "").strip()
        if len(snippet) > 160:
            snippet = snippet[:160] + "..."
        out.append({
            "note_id": n["id"],
            "title": n.get("title") or "(未命名)",
            "snippet": snippet,
            "score": round(float(h.get("score", 0.0)), 4),
        })
    return out


def ask(question: str, session_id: Optional[str] = None) -> Dict[str, Any]:
    """对用户问题执行 RAG 问答，返回 {answer, citations, memories_used} 并写入历史。

    Args:
        question: 用户问题
        session_id: 会话 ID（可选，用于多轮对话和记忆关联）
    """
    question = (question or "").strip()
    if not question:
        return {"answer": "请输入问题。", "citations": [], "memories_used": [], "qa_id": None}

    q_vec = _embed_question(question)

    # 检索长期记忆（与问题向量相似的记忆）
    memories_used: List[Dict[str, Any]] = []
    try:
        mem_hits = database.search_similar_memory(q_vec, top_k=_MAX_MEMORIES)
        # 过滤掉分数太低的
        mem_hits = [m for m in mem_hits if m.get("score", 0) > 0.3]
        memories_used = mem_hits
        # 标记使用
        for m in mem_hits:
            mid = (m.get("memory") or {}).get("id")
            if mid:
                try:
                    database.touch_memory(int(mid))
                except Exception:
                    pass
    except Exception as e:
        logger.warning("记忆检索失败: %s", e)

    # 检索笔记
    hits = database.search_similar(q_vec, top_k=5)
    citations = _make_citations(hits)
    client = _get_client()
    is_demo = client is None

    if not hits and not memories_used:
        answer = "当前知识库中未找到相关笔记。请先同步笔记到监听目录，待处理完成后再次提问。"
        qa_id = database.insert_qa(
            question=question, answer=answer, citations=[], session_id=session_id
        )
        return {"answer": answer, "citations": [], "memories_used": [], "qa_id": qa_id}

    if is_demo:
        titles = "、".join(c["title"] for c in citations) if citations else "(无)"
        mem_str = ""
        if memories_used:
            mem_str = "\n已参考用户记忆：" + "；".join(
                (m.get("memory") or {}).get("content", "")[:50] for m in memories_used
            )
        answer = (
            f"[demo 模式 — 设置 OPENAI_API_KEY 以启用真实问答]\n"
            f"基于向量检索，找到以下 {len(citations)} 条相关笔记：{titles}。"
            f"这些笔记与你的问题在语义上最接近。{mem_str}"
        )
        qa_id = database.insert_qa(
            question=question, answer=answer, citations=citations, session_id=session_id
        )
        return {
            "answer": answer,
            "citations": citations,
            "memories_used": memories_used,
            "qa_id": qa_id,
        }

    # 真实 RAG 调用
    try:
        cfg = get_config()
        memory_ctx = _build_memory_context(memories_used)
        history_ctx = _build_history_context(session_id, question)
        notes_ctx = _build_context(hits)

        parts = []
        if memory_ctx:
            parts.append(memory_ctx)
        if history_ctx:
            parts.append(history_ctx)
        parts.append(f"=== 笔记参考 ===\n{notes_ctx}")
        parts.append(f"用户问题：{question}")
        user_msg = "\n".join(parts)

        resp = client.chat.completions.create(
            model=cfg.QA_MODEL or cfg.LLM_MODEL,
            messages=[
                {"role": "system", "content": _SYSTEM_PROMPT},
                {"role": "user", "content": user_msg},
            ],
            temperature=0.2,
            max_tokens=1000,
        )
        answer = (resp.choices[0].message.content or "").strip()
    except Exception as e:
        logger.exception("LLM 问答失败: %s", e)
        answer = f"问答生成失败：{e}"

    qa_id = database.insert_qa(
        question=question, answer=answer, citations=citations, session_id=session_id
    )
    return {
        "answer": answer,
        "citations": citations,
        "memories_used": memories_used,
        "qa_id": qa_id,
    }


def get_history(limit: int = 50, offset: int = 0, session_id: Optional[str] = None) -> List[Dict[str, Any]]:
    """返回问答历史。"""
    return database.get_qa_history(limit=limit, offset=offset, session_id=session_id)


# ---------------------------------------------------------------------------
# 自我成长：从反馈中提取记忆
# ---------------------------------------------------------------------------
def learn_from_feedback(qa_id: int, rating: str, correction: Optional[str]) -> Optional[int]:
    """从用户反馈中学习，把可记忆的点存入 user_memory。

    - rating='up'：提升该 QA 相关记忆权重（若有）
    - rating='down' + correction：把 correction 作为 'correction' 类型记忆存入

    Returns: 新建记忆 id（若创建）；否则 None
    """
    if rating == "down" and correction and correction.strip():
        # 把用户的修正作为长期记忆
        try:
            client = _get_client()
            embedding = None
            if client is not None:
                embedding = _embed_text(client, correction.strip())
            memory_id = database.insert_memory(
                type="correction",
                content=correction.strip(),
                source="feedback",
                weight=0.8,  # 用户修正权重较高
                embedding=embedding,
                related_qa_id=qa_id,
            )
            logger.info("从反馈中学习：新增修正记忆 id=%s (qa_id=%s)", memory_id, qa_id)
            return memory_id
        except Exception as e:
            logger.warning("从反馈提取记忆失败: %s", e)
            return None
    elif rating == "up":
        # 点赞：找该 QA 引用过的笔记，提升相关记忆权重
        try:
            qa = database.get_qa(qa_id)
            if not qa:
                return None
            citations = qa.get("citations") or []
            # 提升所有 correction 类型记忆的权重（轻微）
            memories = database.list_memory(type="correction", limit=50)
            for m in memories:
                if m.get("related_qa_id") == qa_id:
                    new_weight = min(1.0, float(m.get("weight", 0.5)) + 0.05)
                    database.update_memory(m["id"], weight=new_weight)
            return None
        except Exception as e:
            logger.warning("点赞反馈处理失败: %s", e)
            return None
    return None


def add_manual_memory(
    type: str, content: str, weight: float = 0.5
) -> int:
    """手动添加一条长期记忆。返回 memory_id。"""
    client = _get_client()
    embedding = None
    if client is not None:
        try:
            embedding = _embed_text(client, content)
        except Exception as e:
            logger.warning("记忆向量化失败: %s", e)
    return database.insert_memory(
        type=type,
        content=content,
        source="manual",
        weight=weight,
        embedding=embedding,
    )

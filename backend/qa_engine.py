"""RAG 问答引擎。

ask(question) 流程：
  1. 把问题向量化（无 key 时用 demo 随机向量）
  2. 在全库 done 笔记中向量检索 top 5
  3. 组装 RAG 上下文（标题/摘要/OCR 片段）
  4. 调 GPT-4o chat completion，要求只依据笔记回答并引用 note id
  5. 返回 {answer, citations:[{note_id, title, snippet}]}
  6. 写入 qa_history

Demo 模式（无 key）：返回 canned 答案，列出检索到的笔记标题。
"""
from __future__ import annotations

import logging
import random
from typing import Any, Dict, List

import database
from config import get_config
from ocr_processor import _demo_embedding, _get_client

logger = logging.getLogger("brain.qa")

_SYSTEM_PROMPT = (
    "你是 Brain 笔记知识库的问答助手。请【仅】依据下方提供的笔记内容回答用户问题。"
    "如果笔记中没有相关信息，请明确说明「当前知识库中未找到相关笔记」。"
    "回答时在句末用 [note_id] 形式引用来源笔记的 id，例如 [12]。"
    "保持回答简洁、准确，不要编造笔记中不存在的内容。"
)


def _embed_question(question: str) -> List[float]:
    """把问题转成向量。无 key 时返回 demo 随机向量。"""
    client = _get_client()
    if client is None:
        return _demo_embedding()
    cfg = get_config()
    resp = client.embeddings.create(model=cfg.EMBEDDING_MODEL, input=question)
    return list(resp.data[0].embedding)


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


def ask(question: str) -> Dict[str, Any]:
    """对用户问题执行 RAG 问答，返回 {answer, citations} 并写入历史。"""
    question = (question or "").strip()
    if not question:
        return {"answer": "请输入问题。", "citations": []}

    q_vec = _embed_question(question)
    hits = database.search_similar(q_vec, top_k=5)
    citations = _make_citations(hits)
    client = _get_client()
    is_demo = client is None

    if not hits:
        answer = "当前知识库中未找到相关笔记。请先同步笔记到监听目录，待处理完成后再次提问。"
        qa_id = database.insert_qa(question=question, answer=answer, citations=[])
        return {"answer": answer, "citations": [], "qa_id": qa_id}

    if is_demo:
        titles = "、".join(c["title"] for c in citations)
        answer = (
            f"[demo 模式 — 设置 OPENAI_API_KEY 以启用真实问答]\n"
            f"基于向量检索，找到以下 {len(citations)} 条相关笔记：{titles}。"
            f"这些笔记与你的问题在语义上最接近。"
        )
        qa_id = database.insert_qa(question=question, answer=answer, citations=citations)
        return {"answer": answer, "citations": citations, "qa_id": qa_id}

    # 真实 RAG 调用
    try:
        cfg = get_config()
        context = _build_context(hits)
        user_msg = f"参考笔记：\n{context}\n\n用户问题：{question}"
        resp = client.chat.completions.create(
            model=cfg.QA_MODEL or cfg.LLM_MODEL,
            messages=[
                {"role": "system", "content": _SYSTEM_PROMPT},
                {"role": "user", "content": user_msg},
            ],
            temperature=0.2,
            max_tokens=800,
        )
        answer = (resp.choices[0].message.content or "").strip()
    except Exception as e:
        logger.exception("LLM 问答失败: %s", e)
        answer = f"问答生成失败：{e}"
        # 仍记录历史与引用，便于排查

    qa_id = database.insert_qa(question=question, answer=answer, citations=citations)
    return {"answer": answer, "citations": citations, "qa_id": qa_id}


def get_history(limit: int = 50, offset: int = 0) -> List[Dict[str, Any]]:
    """返回问答历史。"""
    return database.get_qa_history(limit=limit, offset=offset)

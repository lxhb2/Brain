"""RAG 问答引擎（带长期记忆 + 自我成长 + 轻量 Agent）。

ask(question, session_id) 流程（轻量 tool calling Agent）：
  1. 把问题向量化
  2. 预检索：先做一轮笔记 + 记忆向量检索，把结果作为初始上下文
  3. 调 LLM，附带 3 个 tool：search_notes / search_memory / add_memory
     - LLM 可主动调 tool 补充信息（如换关键词再搜笔记、检索特定类型记忆）
     - LLM 可主动调 add_memory 把"用户提到的偏好"存为长期记忆（自我成长）
     - 限制单轮最多 2 次 tool 调用，避免无限循环
  4. LLM 给出最终答案，要求用 [note_id] 引用来源
  5. 写入 qa_history（带 session_id），同步 upsert qa_sessions

自我成长：
  - 反馈 down + correction → 存为 correction 记忆（weight=0.8）
  - 反馈 up → 提升相关记忆权重
  - LLM 主动调 add_memory → 自动学习用户偏好
"""
from __future__ import annotations

import json
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
    "如果用户长期记忆中有相关偏好或事实，请优先参考。\n\n"
    "你可以主动调用以下工具来补充信息或学习用户偏好：\n"
    "- search_notes：用新的关键词重新检索笔记（当初始结果不够时用）\n"
    "- search_memory：检索特定类型的长期记忆\n"
    "- add_memory：把用户提到的偏好、术语、事实存为长期记忆（自我成长）\n"
    "限制：单次回答最多调用 3 次工具，避免无限循环。"
)

# 多轮对话最多回溯几轮
_MAX_HISTORY_TURNS = 5
# 记忆检索 top k
_MAX_MEMORIES = 5
# Agent 单轮最多调用 tool 的次数
_MAX_TOOL_CALLS = 3

# 工具定义（OpenAI tool calling 格式）
_TOOLS = [
    {
        "type": "function",
        "function": {
            "name": "search_notes",
            "description": "用关键词重新检索笔记。当初始检索结果不够或不相关时调用。",
            "parameters": {
                "type": "object",
                "properties": {
                    "query": {
                        "type": "string",
                        "description": "检索关键词或问题"
                    },
                    "top_k": {
                        "type": "integer",
                        "description": "返回条数，默认 5",
                        "default": 5
                    }
                },
                "required": ["query"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "search_memory",
            "description": "检索用户长期记忆。可按类型过滤。",
            "parameters": {
                "type": "object",
                "properties": {
                    "query": {
                        "type": "string",
                        "description": "检索关键词"
                    },
                    "type": {
                        "type": "string",
                        "enum": ["preference", "fact", "correction", "term", "ocr_correction", "ocr_addition"],
                        "description": "记忆类型过滤（可选）"
                    }
                },
                "required": ["query"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "add_memory",
            "description": "把用户提到的偏好、术语、事实存为长期记忆。"
                           "当用户明确表达'我喜欢'、'我习惯'、'记住...'等意图时调用。",
            "parameters": {
                "type": "object",
                "properties": {
                    "type": {
                        "type": "string",
                        "enum": ["preference", "fact", "term"],
                        "description": "记忆类型：preference=用户偏好, fact=已知事实, term=常用术语"
                    },
                    "content": {
                        "type": "string",
                        "description": "记忆内容（简短自然语言）"
                    }
                },
                "required": ["type", "content"]
            }
        }
    }
]


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
            "ocr_correction": "OCR 修正",
            "ocr_addition": "OCR 补充",
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


# ---------------------------------------------------------------------------
# Tool 实现
# ---------------------------------------------------------------------------
def _tool_search_notes(query: str, top_k: int = 5) -> str:
    """Tool: 用关键词重新检索笔记。返回 JSON 字符串。"""
    try:
        client = _get_client()
        if client is None:
            return json.dumps({"error": "demo 模式，无法检索"}, ensure_ascii=False)
        vec = _embed_text(client, query)
        hits = database.search_similar(vec, top_k=top_k)
        if not hits:
            return json.dumps({"found": 0, "notes": []}, ensure_ascii=False)
        notes_out = []
        for h in hits:
            n = h["note"]
            notes_out.append({
                "id": n["id"],
                "title": n.get("title") or "(未命名)",
                "summary": (n.get("summary") or "")[:200],
                "ocr_text_preview": (n.get("ocr_text") or "")[:400],
                "score": round(float(h.get("score", 0.0)), 4),
            })
        return json.dumps({"found": len(notes_out), "notes": notes_out}, ensure_ascii=False)
    except Exception as e:
        logger.warning("tool search_notes 失败: %s", e)
        return json.dumps({"error": str(e)}, ensure_ascii=False)


def _tool_search_memory(query: str, type: Optional[str] = None) -> str:
    """Tool: 检索长期记忆。返回 JSON 字符串。"""
    try:
        client = _get_client()
        if client is None:
            return json.dumps({"error": "demo 模式，无法检索"}, ensure_ascii=False)
        vec = _embed_text(client, query)
        hits = database.search_similar_memory(vec, top_k=5)
        hits = [m for m in hits if m.get("score", 0) > 0.25]
        if type:
            hits = [m for m in hits if (m.get("memory") or {}).get("type") == type]
        if not hits:
            return json.dumps({"found": 0, "memories": []}, ensure_ascii=False)
        mem_out = []
        for m in hits:
            d = m.get("memory", m)
            mem_out.append({
                "id": d.get("id"),
                "type": d.get("type"),
                "content": d.get("content"),
                "weight": d.get("weight"),
                "score": round(float(m.get("score", 0.0)), 4),
            })
        return json.dumps({"found": len(mem_out), "memories": mem_out}, ensure_ascii=False)
    except Exception as e:
        logger.warning("tool search_memory 失败: %s", e)
        return json.dumps({"error": str(e)}, ensure_ascii=False)


def _tool_add_memory(type: str, content: str) -> str:
    """Tool: 新增长期记忆。返回 JSON 字符串。"""
    try:
        if type not in ("preference", "fact", "term"):
            return json.dumps({"error": f"不支持的 type: {type}"}, ensure_ascii=False)
        client = _get_client()
        embedding = None
        if client is not None:
            try:
                embedding = _embed_text(client, content)
            except Exception:
                pass
        memory_id = database.insert_memory(
            type=type,
            content=content.strip(),
            source="auto_learn",
            weight=0.6,
            embedding=embedding,
        )
        logger.info("Agent 自动学习：新增 %s 记忆 id=%s content=%s",
                    type, memory_id, content[:50])
        return json.dumps({"ok": True, "memory_id": memory_id}, ensure_ascii=False)
    except Exception as e:
        logger.warning("tool add_memory 失败: %s", e)
        return json.dumps({"error": str(e)}, ensure_ascii=False)


def _execute_tool_call(tool_name: str, arguments: Dict[str, Any]) -> str:
    """执行一次 tool 调用，返回结果字符串。"""
    if tool_name == "search_notes":
        return _tool_search_notes(
            query=arguments.get("query", ""),
            top_k=arguments.get("top_k", 5),
        )
    elif tool_name == "search_memory":
        return _tool_search_memory(
            query=arguments.get("query", ""),
            type=arguments.get("type"),
        )
    elif tool_name == "add_memory":
        return _tool_add_memory(
            type=arguments.get("type", "preference"),
            content=arguments.get("content", ""),
        )
    return json.dumps({"error": f"未知工具: {tool_name}"}, ensure_ascii=False)


def ask(question: str, session_id: Optional[str] = None) -> Dict[str, Any]:
    """对用户问题执行 RAG 问答（轻量 Agent），返回 {answer, citations, memories_used, tools_used} 并写入历史。

    Args:
        question: 用户问题
        session_id: 会话 ID（可选，用于多轮对话和记忆关联）
    """
    question = (question or "").strip()
    if not question:
        return {"answer": "请输入问题。", "citations": [], "memories_used": [], "qa_id": None, "tools_used": []}

    q_vec = _embed_question(question)

    # 预检索长期记忆
    memories_used: List[Dict[str, Any]] = []
    try:
        mem_hits = database.search_similar_memory(q_vec, top_k=_MAX_MEMORIES)
        mem_hits = [m for m in mem_hits if m.get("score", 0) > 0.3]
        memories_used = mem_hits
        for m in mem_hits:
            mid = (m.get("memory") or {}).get("id")
            if mid:
                try:
                    database.touch_memory(int(mid))
                except Exception:
                    pass
    except Exception as e:
        logger.warning("记忆检索失败: %s", e)

    # 预检索笔记
    hits = database.search_similar(q_vec, top_k=5)
    citations = _make_citations(hits)
    client = _get_client()
    is_demo = client is None

    if not hits and not memories_used:
        answer = "当前知识库中未找到相关笔记。请先同步笔记到监听目录，待处理完成后再次提问。"
        qa_id = database.insert_qa(
            question=question, answer=answer, citations=[], session_id=session_id
        )
        return {"answer": answer, "citations": [], "memories_used": [], "qa_id": qa_id, "tools_used": []}

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
            "tools_used": [],
        }

    # 真实 RAG + 轻量 Agent
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

    messages = [
        {"role": "system", "content": _SYSTEM_PROMPT},
        {"role": "user", "content": user_msg},
    ]
    tools_used: List[Dict[str, Any]] = []
    answer = ""

    try:
        # Agent loop：最多 _MAX_TOOL_CALLS 次 tool 调用
        for iteration in range(_MAX_TOOL_CALLS + 1):
            resp = client.chat.completions.create(
                model=cfg.QA_MODEL or cfg.LLM_MODEL,
                messages=messages,
                tools=_TOOLS,
                temperature=0.2,
                max_tokens=1200,
                timeout=60,
            )
            msg = resp.choices[0].message

            # 没有 tool_calls → 最终答案
            if not msg.tool_calls:
                answer = (msg.content or "").strip()
                break

            # 把 assistant 的 tool_call 消息加入对话
            messages.append({
                "role": "assistant",
                "content": msg.content or "",
                "tool_calls": [
                    {
                        "id": tc.id,
                        "type": "function",
                        "function": {
                            "name": tc.function.name,
                            "arguments": tc.function.arguments,
                        }
                    }
                    for tc in msg.tool_calls
                ]
            })

            # 执行每个 tool_call，把结果加入对话
            for tc in msg.tool_calls:
                tool_name = tc.function.name
                try:
                    args = json.loads(tc.function.arguments or "{}")
                except json.JSONDecodeError:
                    args = {}
                result = _execute_tool_call(tool_name, args)
                tools_used.append({
                    "name": tool_name,
                    "arguments": args,
                    "result_preview": result[:200],
                })
                logger.info("Agent 调用 tool: %s args=%s", tool_name, args)
                messages.append({
                    "role": "tool",
                    "tool_call_id": tc.id,
                    "content": result,
                })

            # 达到上限就强制让 LLM 给最终答案（不再带 tools）
            if iteration == _MAX_TOOL_CALLS - 1:
                resp = client.chat.completions.create(
                    model=cfg.QA_MODEL or cfg.LLM_MODEL,
                    messages=messages,
                    temperature=0.2,
                    max_tokens=1200,
                    timeout=60,
                )
                answer = (resp.choices[0].message.content or "").strip()
                break
        else:
            # 兜底：循环结束仍没答案
            answer = "（Agent 未能给出最终答案，请重试）"

    except Exception as e:
        logger.exception("LLM 问答失败: %s", e)
        answer = f"问答生成失败：{e}"

    # 兜底：循环结束仍没拿到有效答案
    if not answer.strip():
        answer = "（Agent 未能给出最终答案，请重试或换个问法）"

    qa_id = database.insert_qa(
        question=question, answer=answer, citations=citations, session_id=session_id
    )
    return {
        "answer": answer,
        "citations": citations,
        "memories_used": memories_used,
        "qa_id": qa_id,
        "tools_used": tools_used,
    }


def get_history(limit: int = 50, offset: int = 0, session_id: Optional[str] = None) -> List[Dict[str, Any]]:
    """返回问答历史。"""
    return database.get_qa_history(limit=limit, offset=offset, session_id=session_id)


# ---------------------------------------------------------------------------
# 会话管理
# ---------------------------------------------------------------------------
def list_sessions(limit: int = 50) -> List[Dict[str, Any]]:
    """列出所有会话。"""
    return database.list_qa_sessions(limit=limit)


def rename_session(session_id: str, title: str) -> bool:
    """重命名会话。"""
    return database.rename_qa_session(session_id, title)


def delete_session(session_id: str) -> bool:
    """删除会话及其所有问答记录。"""
    return database.delete_qa_session(session_id)


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

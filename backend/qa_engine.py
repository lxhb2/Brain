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

# 知识卡片生成 prompt（QA 完成后异步调用 LLM 生成卡片草稿）
_CARD_GEN_PROMPT = """你是一名知识整理助手。基于下面这次问答，生成一张"知识卡片"草稿。

**问答内容**：
- 用户问题：{question}
- Agent 回答：{answer}
- 引用的笔记（id 与标题）：{citations}

请按以下结构生成卡片（用 JSON 返回，仅返回 JSON，不要额外解释）：

```json
{{
  "title": "卡片标题（5-20字，点明这次问答解决的核心问题）",
  "core_summary": "核心讲了什么：这1-N份资料解决了什么问题、原资料名称、内容提炼（1-2句话）",
  "key_conclusion": "关键结论：用户需要记住的核心知识点（1-3条，用换行分隔）",
  "application_scenario": "能在什么场景下落地使用：具体的应用场景或操作建议（1-2句话）",
  "agent_question": "向用户提一个检验性问题：考察用户是否真理解了这次问答的核心（一个问题，简短，开放式）"
}}
```

要求：
- title 简洁有信息量，不要用"问答总结"这种泛标题
- core_summary 必须提到原资料名称（从 citations 里取标题）
- key_conclusion 是用户"需要记住的"，不是"资料里写了什么"
- agent_question 不要太刁钻，是检验理解而非考试，比如"如果遇到 X 场景，你会怎么做？"
- 如果问答里没有可沉淀的知识（如寒暄、报错），返回 {{"skip": true}}"""


def _generate_card_draft(
    question: str,
    answer: str,
    citations: List[Dict[str, Any]],
) -> Optional[Dict[str, Any]]:
    """调用 LLM 生成知识卡片草稿。

    返回 dict（含 title/core_summary/key_conclusion/application_scenario/agent_question），
    或 {"skip": True}（LLM 判断不值得存档），或 None（调用失败）。
    """
    client = _get_client()
    if client is None:
        return None
    cfg = get_config()
    # 拼接引用笔记信息
    cit_text = "\n".join(
        f"- [{c.get('note_id')}] {c.get('title', '(无标题)')}"
        for c in citations
    ) or "(本次问答未引用具体笔记)"
    prompt = _CARD_GEN_PROMPT.format(
        question=question[:500],
        answer=answer[:2000],
        citations=cit_text,
    )
    try:
        resp = client.chat.completions.create(
            model=cfg.QA_MODEL or cfg.LLM_MODEL,
            messages=[{"role": "user", "content": prompt}],
            temperature=0.2,
            max_tokens=800,
            timeout=30,
        )
        raw = resp.choices[0].message.content or ""
        # 剥离 markdown 代码围栏
        s = raw.strip()
        if s.startswith("```"):
            first_nl = s.find("\n")
            if first_nl != -1:
                s = s[first_nl + 1:]
            if s.endswith("```"):
                s = s[:-3]
            s = s.strip()
        try:
            data = json.loads(s)
        except json.JSONDecodeError:
            logger.warning("卡片草稿 JSON 解析失败: %s", s[:200])
            return None
        if data.get("skip"):
            return {"skip": True}
        # 必填字段校验
        if not data.get("title") or not data.get("core_summary") or not data.get("key_conclusion"):
            logger.warning("卡片草稿缺少必填字段: %s", list(data.keys()))
            return None
        return data
    except Exception as e:
        logger.warning("生成卡片草稿失败: %s", e)
        return None

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
        tool_call_count = 0
        while True:
            # 达到上限：最后一次调用不再带 tools，强制让 LLM 给最终答案
            use_tools = tool_call_count < _MAX_TOOL_CALLS
            resp = client.chat.completions.create(
                model=cfg.QA_MODEL or cfg.LLM_MODEL,
                messages=messages,
                tools=_TOOLS if use_tools else None,
                temperature=0.2,
                max_tokens=1200,
                timeout=60,
            )
            msg = resp.choices[0].message

            # 没有 tool_calls → 最终答案，结束循环
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
                logger.info("Agent 调用 tool [%d/%d]: %s args=%s",
                            tool_call_count + 1, _MAX_TOOL_CALLS, tool_name, args)
                messages.append({
                    "role": "tool",
                    "tool_call_id": tc.id,
                    "content": result,
                })
                tool_call_count += 1
                # 单次 tool_call 数量也达上限就退出
                if tool_call_count >= _MAX_TOOL_CALLS:
                    break

            # 如果已达上限，下一轮循环会因 use_tools=False 强制收尾

    except Exception as e:
        logger.exception("LLM 问答失败: %s", e)
        answer = f"问答生成失败：{e}"

    # 兜底：循环结束仍没拿到有效答案
    if not answer.strip():
        answer = "（Agent 未能给出最终答案，请重试或换个问法）"

    qa_id = database.insert_qa(
        question=question, answer=answer, citations=citations, session_id=session_id
    )

    # 异步生成知识卡片草稿（不阻塞主流程，失败不影响 QA 结果）
    card_draft: Optional[Dict[str, Any]] = None
    try:
        # 只在有 citations 或 memories 时尝试生成（寒暄类直接跳过）
        if citations or memories_used:
            draft = _generate_card_draft(question, answer, citations)
            if draft and not draft.get("skip"):
                # 提取引用的 note_id 列表
                source_note_ids = [c.get("note_id") for c in citations if c.get("note_id")]
                card_draft = {
                    "title": draft.get("title", ""),
                    "core_summary": draft.get("core_summary", ""),
                    "key_conclusion": draft.get("key_conclusion", ""),
                    "application_scenario": draft.get("application_scenario", ""),
                    "agent_question": draft.get("agent_question", ""),
                    "source_note_ids": source_note_ids,
                    "qa_id": qa_id,
                    "session_id": session_id,
                }
    except Exception as e:
        logger.warning("卡片草稿生成失败（不影响主流程）: %s", e)

    return {
        "answer": answer,
        "citations": citations,
        "memories_used": memories_used,
        "qa_id": qa_id,
        "tools_used": tools_used,
        "card_draft": card_draft,
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

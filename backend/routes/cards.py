"""知识卡片接口。

QA 完成后由 qa_engine 生成卡片草稿（含 agent_question），前端弹窗
让用户回答；用户提交后调 /finalize 触发 LLM 评估并补充，最后落库。
卡片-笔记链接基于 source_note_ids 自动建立。
"""
from __future__ import annotations

import json
import logging
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

import database
from config import get_config
from ocr_processor import _get_client

logger = logging.getLogger("brain.routes.cards")

router = APIRouter(prefix="/api/cards", tags=["cards"])


# ---------------------------------------------------------------------------
# 请求模型
# ---------------------------------------------------------------------------
class FinalizeCardRequest(BaseModel):
    """提交用户答案，触发卡片存档。"""
    qa_id: Optional[int] = None
    session_id: Optional[str] = None
    title: str
    core_summary: str
    key_conclusion: str
    application_scenario: str = ""
    agent_question: str = ""
    user_answer: str = ""  # 用户对 agent_question 的回答，可空（跳过）
    source_note_ids: List[int] = []


class UpdateCardRequest(BaseModel):
    """编辑已有卡片。"""
    title: Optional[str] = None
    core_summary: Optional[str] = None
    key_conclusion: Optional[str] = None
    application_scenario: Optional[str] = None
    agent_question: Optional[str] = None
    user_answer: Optional[str] = None
    ai_supplement: Optional[str] = None
    source_note_ids: Optional[List[int]] = None


# ---------------------------------------------------------------------------
# LLM 评估用户答案
# ---------------------------------------------------------------------------
_EVAL_PROMPT = """你是一名知识学习教练。用户刚刚看完一份知识卡片，你提了一个检验性问题，现在要评估用户的回答。

**卡片信息**：
- 标题：{title}
- 关键结论：{key_conclusion}
- 落地场景：{scenario}

**你提的问题**：{question}

**用户的回答**：{user_answer}

请评估用户回答是否正确理解了核心知识点，并给出补充：

1. 如果用户回答正确、抓住了要点：返回 {{"verdict": "correct", "supplement": ""}} 或一句简短肯定。
2. 如果用户回答有偏差、不完整或跳过：返回 {{"verdict": "needs_supplement", "supplement": "标准答案/补充说明（2-4句话）"}}。
3. 不要重复用户已说对的内容，只补缺失的部分。

仅返回 JSON，不要额外解释。"""


def _evaluate_user_answer(
    title: str,
    key_conclusion: str,
    scenario: str,
    question: str,
    user_answer: str,
) -> Dict[str, str]:
    """调 LLM 评估用户答案，返回 {verdict, supplement}。失败时返回 needs_supplement + 空补充。"""
    client = _get_client()
    if client is None:
        return {"verdict": "needs_supplement", "supplement": ""}
    cfg = get_config()
    prompt = _EVAL_PROMPT.format(
        title=title[:100],
        key_conclusion=key_conclusion[:500],
        scenario=scenario[:300] or "(未提供)",
        question=question[:200] or "(未提问)",
        user_answer=user_answer.strip()[:500] or "(用户跳过)",
    )
    try:
        resp = client.chat.completions.create(
            model=cfg.QA_MODEL or cfg.LLM_MODEL,
            messages=[{"role": "user", "content": prompt}],
            temperature=0.2,
            max_tokens=2000,
            timeout=120,
        )
        raw = resp.choices[0].message.content or ""
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
            return {
                "verdict": data.get("verdict", "needs_supplement"),
                "supplement": data.get("supplement", "") or "",
            }
        except json.JSONDecodeError:
            logger.warning("LLM 评估 JSON 解析失败: %s", s[:200])
            return {"verdict": "needs_supplement", "supplement": ""}
    except Exception as e:
        logger.warning("LLM 评估失败: %s", e)
        return {"verdict": "needs_supplement", "supplement": ""}


# ---------------------------------------------------------------------------
# 路由
# ---------------------------------------------------------------------------
@router.get("")
def list_cards(limit: int = 50, offset: int = 0, session_id: Optional[str] = None):
    """列出知识卡片。"""
    res = database.list_knowledge_cards(limit=limit, offset=offset, session_id=session_id)
    return res


@router.get("/{card_id}")
def get_card(card_id: int):
    """获取卡片详情。"""
    card = database.get_knowledge_card(card_id)
    if not card:
        raise HTTPException(status_code=404, detail="卡片不存在")
    # 附带链接信息
    links = database.get_card_links_for(card_id)
    return {**card, "links": links}


@router.post("/finalize")
def finalize_card(body: FinalizeCardRequest):
    """提交用户答案 + 触发 LLM 评估 + 落库。

    - 如果 user_answer 为空（用户跳过），直接由 LLM 补充标准答案
    - 如果 user_answer 非空，LLM 评估是否正确，错误/不完整时补充
    - 落库后基于 source_note_ids 自动建立 card→note 链接
    """
    # 评估用户答案
    ai_supplement = ""
    verdict = "skipped"
    if body.agent_question:
        if body.user_answer.strip():
            result = _evaluate_user_answer(
                title=body.title,
                key_conclusion=body.key_conclusion,
                scenario=body.application_scenario,
                question=body.agent_question,
                user_answer=body.user_answer,
            )
            verdict = result.get("verdict", "needs_supplement")
            ai_supplement = result.get("supplement", "")
        else:
            # 用户跳过，让 LLM 直接给标准答案
            result = _evaluate_user_answer(
                title=body.title,
                key_conclusion=body.key_conclusion,
                scenario=body.application_scenario,
                question=body.agent_question,
                user_answer="",  # 空答案触发补充
            )
            verdict = "skipped"
            ai_supplement = result.get("supplement", "")

    # 插入卡片
    card_id = database.insert_knowledge_card(
        qa_id=body.qa_id,
        session_id=body.session_id,
        title=body.title,
        core_summary=body.core_summary,
        key_conclusion=body.key_conclusion,
        application_scenario=body.application_scenario,
        agent_question=body.agent_question,
        user_answer=body.user_answer,
        ai_supplement=ai_supplement,
        source_note_ids=body.source_note_ids,
        status="finalized",
    )
    if not card_id:
        raise HTTPException(status_code=500, detail="卡片落库失败")

    # 自动建立 card→note 链接
    linked_notes = 0
    for note_id in body.source_note_ids:
        ok = database.insert_card_link(
            source_type="card",
            source_id=card_id,
            target_type="note",
            target_id=int(note_id),
            weight=1.0,
            reason="卡片引用的笔记",
        )
        if ok:
            linked_notes += 1

    logger.info("卡片 #%d 已存档 (verdict=%s, linked_notes=%d)", card_id, verdict, linked_notes)

    return {
        "card_id": card_id,
        "verdict": verdict,
        "ai_supplement": ai_supplement,
        "linked_notes": linked_notes,
    }


@router.patch("/{card_id}")
def update_card(card_id: int, body: UpdateCardRequest):
    """编辑已有卡片。"""
    existing = database.get_knowledge_card(card_id)
    if not existing:
        raise HTTPException(status_code=404, detail="卡片不存在")
    fields = body.model_dump(exclude_none=True)
    if not fields:
        raise HTTPException(status_code=400, detail="未提供要更新的字段")
    ok = database.update_knowledge_card(card_id, **fields)
    if not ok:
        raise HTTPException(status_code=500, detail="更新失败")
    # 如果 source_note_ids 改了，重建链接
    if body.source_note_ids is not None:
        # 简化处理：不删旧链接，只补新链接（INSERT OR IGNORE）
        for note_id in body.source_note_ids:
            database.insert_card_link(
                source_type="card", source_id=card_id,
                target_type="note", target_id=int(note_id),
                weight=1.0, reason="卡片引用的笔记",
            )
    return {"card_id": card_id, "updated": True}


@router.delete("/{card_id}")
def delete_card(card_id: int):
    """删除卡片（级联清理 card_links）。"""
    ok = database.delete_knowledge_card(card_id)
    if not ok:
        raise HTTPException(status_code=404, detail="卡片不存在")
    return {"deleted": True, "card_id": card_id}

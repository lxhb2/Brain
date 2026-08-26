"""成长运营 Agent：入库分诊、经验结构化、每日审核和价值指标。"""
from __future__ import annotations

import json
import logging
from datetime import datetime
from typing import Any, Dict, Optional
from zoneinfo import ZoneInfo

import database
from config import get_config
from ocr_processor import _completion_text, _get_client, _strip_fences

logger = logging.getLogger("brain.growth")
_TZ_SHANGHAI = ZoneInfo("Asia/Shanghai")


def _local_date(target_date: Optional[str] = None) -> str:
    return target_date or datetime.now(_TZ_SHANGHAI).strftime("%Y-%m-%d")


def _parse_json(raw: str) -> Dict[str, Any]:
    cleaned = _strip_fences(raw)
    try:
        return json.loads(cleaned)
    except json.JSONDecodeError:
        start, end = cleaned.find("{"), cleaned.rfind("}")
        if start >= 0 and end > start:
            try:
                return json.loads(cleaned[start:end + 1])
            except json.JSONDecodeError:
                pass
    return {}


def _preview(note: Dict[str, Any], limit: int = 1200) -> str:
    parts = [note.get("title") or "", note.get("summary") or "", (note.get("ocr_text") or "")[:limit]]
    return "\n".join(part for part in parts if part)


def _triage_prompt(content: str) -> str:
    return f"""你是个人知识库的入库分诊官。判断下面内容是否属于用户的实操经验。

分类规则：
- practice：用户做过、验证过、写出条件/结果/下一步的内容。
- reference：书、课程、别人的方法、一般资料；先放仓库区。
- noise：寒暄、截图说明、临时信息。

仅返回 JSON：
{{
  "knowledge_kind": "practice|reference|noise",
  "practice_status": "done|attempted|planned|external|unknown",
  "context_condition": "什么场景或条件下成立，可为空",
  "action": "具体动作，可为空",
  "consequence": "预期后果或实际结果，可为空",
  "evidence": "验证证据，可为空",
  "next_action": "下一个最小实验或行动，可为空",
  "confidence": 0.5
}}

没有“我做了/结果是/下次要”这类证据时，优先判为 reference，不要美化成 practice。

笔记内容：
{content}"""


def triage_note(note: Dict[str, Any]) -> bool:
    """用 LLM 给单条笔记做入库分诊。"""
    client = _get_client()
    if not client:
        return False
    cfg = get_config()
    try:
        resp = client.chat.completions.create(
            model=cfg.QA_MODEL or cfg.LLM_MODEL,
            messages=[{"role": "user", "content": _triage_prompt(_preview(note))}],
            temperature=0.1,
            max_tokens=900,
            timeout=120,
        )
        data = _parse_json(_completion_text(resp.choices[0].message))
        kind = data.get("knowledge_kind")
        if kind not in ("practice", "reference", "noise"):
            return False
        status = data.get("practice_status")
        if kind == "reference":
            status = "external"
        elif kind == "noise":
            status = "unknown"
        elif status not in ("done", "attempted", "planned", "unknown"):
            status = "attempted"
        database.update_note_insight(
            int(note["id"]),
            knowledge_kind=kind,
            practice_status=status,
            condition_text=str(data.get("context_condition") or "")[:1000],
            action_text=str(data.get("action") or "")[:1000],
            consequence_text=str(data.get("consequence") or "")[:1000],
            evidence_text=str(data.get("evidence") or "")[:1000],
            next_action_text=str(data.get("next_action") or "")[:1000],
            confidence=float(data.get("confidence") or 0.5),
        )
        model_name = cfg.QA_MODEL or cfg.LLM_MODEL
        database.insert_activity(
            event_type="model",
            message=f"{model_name} 分诊笔记 #{note['id']} 为 {kind}",
            model=model_name,
            note_id=int(note["id"]),
            file_name=note.get("file_path"),
        )
        return True
    except Exception as exc:
        logger.warning("分诊笔记 %s 失败: %s", note.get("id"), exc)
        return False


def triage_pending_notes(limit: int = 3) -> Dict[str, int]:
    """每次只处理少量待分诊笔记，避免后台任务占满本地模型。"""
    notes = database.list_unclassified_notes(limit=limit)
    ok = sum(1 for note in notes if triage_note(note))
    return {"found": len(notes), "triaged": ok}


def generate_daily_review(target_date: Optional[str] = None) -> Optional[Dict[str, Any]]:
    """生成某天的成长审核：已沉淀、错题本和调整方案。"""
    review_date = _local_date(target_date)
    notes = database.list_notes_by_date(review_date)
    cards = database.list_knowledge_cards(limit=30)["items"]
    due_cards = [card for card in database.list_due_cards(limit=10) if card.get("agent_question")]
    stats = database.get_stats()["growth"]
    if not notes and not cards:
        return None

    notes_text = "\n\n".join(
        f"#{n['id']} {n.get('title') or '(未命名)'}\n"
        f"类型：{n.get('knowledge_kind') or 'unclassified'} / 状态：{n.get('practice_status') or 'unknown'}\n"
        f"摘要：{n.get('summary') or ''}\n条件：{n.get('condition_text') or ''}\n"
        f"动作：{n.get('action_text') or ''}\n结果：{n.get('consequence_text') or ''}\n"
        f"证据：{n.get('evidence') or ''}"
        for n in notes[:20]
    ) or "(当天没有新笔记)"
    cards_text = "\n\n".join(
        f"卡片 #{c['id']} {c.get('title')}\n结论：{c.get('key_conclusion')}\n"
        f"回答：{c.get('user_answer') or '(无)'}\nAI补充：{c.get('ai_supplement') or ''}"
        for c in cards[:15]
    ) or "(还没有知识卡片)"
    due_text = "\n".join(
        f"- #{c['id']} {c.get('title')}: {c.get('agent_question')}" for c in due_cards
    ) or "(暂无到期复验)"

    client = _get_client()
    if not client:
        return None
    cfg = get_config()
    prompt = f"""你是用户的成长审计导师，不是资料收藏助手。请对照记录审核用户今天有没有真正进步。

要求：
1. 只承认有证据、条件或行动的活知识。
2. 找出理解偏差、重复出现但没执行的事、验证失败的知识。
3. 调整方案必须小、具体、明天能做。
4. 不要复述所有笔记，不要写空泛鼓励。

返回 JSON：
{{
  "headline": "一句话成长结论",
  "kept": [{{"title": "沉淀点", "why": "为什么值得保留"}}],
  "mistakes": [{{"title": "错题或偏差", "correction": "应该怎么修正", "next_action": "具体修正动作"}}],
  "adjustments": ["明天可执行的最小调整"],
  "review_questions": ["需要用户回答的检验问题"],
  "metrics": {{"density": 0.0, "frequency": 0.0, "depth": 0.0}},
  "skill_updates": [{{"skill": "技能名", "level": "novice|learning|validated|shaky|wrong", "reason": "判定原因"}}]
}}

当前系统指标：{json.dumps(stats, ensure_ascii=False)}
到期复验：{due_text}

今日笔记：
{notes_text}

近期卡片：
{cards_text}"""

    try:
        resp = client.chat.completions.create(
            model=cfg.QA_MODEL or cfg.LLM_MODEL,
            messages=[
                {"role": "system", "content": "你严格、具体、反对无效收藏，帮助用户把知识变成行为改进。"},
                {"role": "user", "content": prompt},
            ],
            temperature=0.2,
            max_tokens=2500,
            timeout=180,
        )
        content = _parse_json(_completion_text(resp.choices[0].message))
        if not content:
            logger.warning("每日成长审核 JSON 解析失败")
            return None
        content["system_metrics"] = stats
        content["due_card_ids"] = [int(c["id"]) for c in due_cards]
        model_name = cfg.QA_MODEL or cfg.LLM_MODEL
        review_id = database.upsert_growth_review(
            review_date=review_date,
            content=content,
            model=model_name,
            note_ids=[int(n["id"]) for n in notes],
        )
        database.insert_activity(
            event_type="model",
            message=f"{model_name} 完成 {review_date} 成长审核，覆盖 {len(notes)} 条笔记 / {len(cards)} 张卡片",
            model=model_name,
        )
        return {"review_id": review_id, "notes_count": len(notes), "cards_count": len(cards)}
    except Exception as exc:
        logger.exception("每日成长审核失败: %s", exc)
        return None


def run_daily_maintenance() -> Dict[str, Any]:
    """后台定时入口：先分诊少量积压，再生成当日审核。"""
    triage = triage_pending_notes(limit=3)
    review = generate_daily_review()
    return {"triage": triage, "review": review}

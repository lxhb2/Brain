"""轻量联网验证 / 辩论模块。

联网结果只作为本次报告的临时证据，不写入笔记库。
"""
from __future__ import annotations

import html
import json
import logging
import re
from typing import Any, Dict, List, Optional

import requests

import database
from config import get_config
from ocr_processor import _get_client

logger = logging.getLogger("brain.web_research")

_BING_URL = "https://www.bing.com/search"
_SEARCH_TIMEOUT = 10
_MAX_QUERIES = 2
_MAX_RESULTS_PER_QUERY = 3
_MAX_EVIDENCE = 6
_MAX_HISTORY_TURNS = 5
_MAX_HISTORY_CHARS = 2400
_HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/126.0 Safari/537.36",
    "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
}


def _decode_json(raw: str) -> Optional[Dict[str, Any]]:
    s = (raw or "").strip()
    if s.startswith("```"):
        first_nl = s.find("\n")
        if first_nl != -1:
            s = s[first_nl + 1:]
        if s.endswith("```"):
            s = s[:-3]
        s = s.strip()

    match = re.search(r"\{.*\}", s, re.DOTALL)
    candidates = [match.group(0)] if match else []
    candidates.append(s)
    for candidate in candidates:
        try:
            data = json.loads(candidate)
            if isinstance(data, dict):
                return data
        except json.JSONDecodeError:
            continue
    return None


def _strip_html(raw: str) -> str:
    text = re.sub(r"<[^>]+>", " ", raw or "")
    return html.unescape(re.sub(r"\s+", " ", text)).strip()


def _search_bing(query: str) -> List[Dict[str, str]]:
    """读取 Bing HTML 结果页，只取标题、链接和摘要。"""
    response = requests.get(
        _BING_URL,
        params={"q": query, "count": 6},
        headers=_HEADERS,
        timeout=_SEARCH_TIMEOUT,
    )
    response.raise_for_status()
    segments = re.split(r'<li[^>]+class=["\'][^"\']*b_algo', response.text, flags=re.I)[1:]
    results: List[Dict[str, str]] = []
    for segment in segments[:4]:
        title_match = re.search(
            r'<h2[^>]*>\s*<a[^>]+href=["\']([^"\']+)["\'][^>]*>(.*?)</a>',
            segment,
            flags=re.I | re.S,
        )
        if not title_match:
            continue
        url = html.unescape(title_match.group(1))
        title = _strip_html(title_match.group(2))
        if not url.startswith("http") or not title:
            continue
        snippet_match = re.search(
            r'<p[^>]+class=["\'][^"\']*b_lineclamp[^"\']*["\'][^>]*>(.*?)</p>',
            segment,
            flags=re.I | re.S,
        )
        snippet = _strip_html(snippet_match.group(1)) if snippet_match else ""
        results.append({"title": title[:160], "url": url, "snippet": snippet[:360]})
    return results


def _collect_web_evidence(queries: List[str]) -> tuple[List[Dict[str, str]], str]:
    queries = [str(q or "").strip() for q in queries if str(q or "").strip()][:_MAX_QUERIES]
    evidence: List[Dict[str, str]] = []
    seen_urls: set[str] = set()
    errors: List[str] = []
    for query in queries:
        try:
            for item in _search_bing(query)[:_MAX_RESULTS_PER_QUERY]:
                url = item["url"]
                if url in seen_urls:
                    continue
                seen_urls.add(url)
                evidence.append({**item, "query": query})
                if len(evidence) >= _MAX_EVIDENCE:
                    break
        except Exception as exc:
            logger.warning("联网搜索失败 query=%s: %s", query, exc)
            errors.append(str(exc))
        if len(evidence) >= _MAX_EVIDENCE:
            break
    return evidence, "; ".join(errors[:2])


def _history_context(
    session_id: Optional[str],
    qa_id: Optional[int],
) -> tuple[str, List[Dict[str, Any]]]:
    if not session_id:
        return "", []
    try:
        history = database.get_qa_history(limit=10, offset=0, session_id=session_id)
    except Exception:
        logger.debug("读取问答历史失败", exc_info=True)
        return "", []
    if qa_id is not None:
        history = [h for h in history if int(h.get("id") or 0) <= int(qa_id)]
    history = history[-_MAX_HISTORY_TURNS:]
    lines: List[str] = []
    for h in history:
        question = str(h.get("question") or "").strip()
        answer = str(h.get("answer") or "").strip()
        if not question and not answer:
            continue
        lines.append(f"用户：{question}\nBrain：{answer[:520]}")
    text = "\n\n".join(lines)[:_MAX_HISTORY_CHARS]
    return text, history


def _normalize_query(value: Any) -> str:
    return re.sub(r"\s+", " ", str(value or "")).strip(" ：:，,")[:80]


def _plan_research(
    client: Any,
    current_question: str,
    current_answer: str,
    history_text: str,
    citations: List[Dict[str, Any]],
) -> Dict[str, Any]:
    plain_answer = re.sub(r"#+\s*", "", current_answer or "")
    fallback_claim = (current_question or plain_answer).strip().replace("\n", " ")[:160]
    fallback = {
        "claim": fallback_claim,
        "keywords": [],
        "queries": [
            f"{fallback_claim} 证据 研究",
            f"{fallback_claim} 反例 缺点 风险",
        ],
        "debate_recommended": False,
    }
    if client is None or not fallback_claim:
        return fallback

    cfg = get_config()
    prompt = f"""你是研究规划器。先理解近期对话和当前回答，提炼本次真正需要检验的观点。

【近期对话】
{history_text or "(无)"}

【当前问题】
{current_question or "(无)"}

【当前回答】
{current_answer[:1800]}

【本地笔记线索】
{_citations_text(citations)}

只返回 JSON，不要解释：
{{
  "claim": "一句话核心观点或假设",
  "keywords": ["关键词1", "关键词2"],
  "support_query": "支持方检索词",
  "oppose_query": "反对方检索词",
  "debate_recommended": true
}}

限制：keywords 最多 5 个；support_query 和 oppose_query 各不能超过 20 个字；只在存在真实分歧或证据冲突时把 debate_recommended 设为 true。"""
    try:
        resp = client.chat.completions.create(
            model=cfg.QA_MODEL or cfg.LLM_MODEL,
            messages=[{"role": "user", "content": prompt}],
            temperature=0.1,
            max_tokens=700,
            timeout=45,
        )
        data = _decode_json(resp.choices[0].message.content or "")
    except Exception as exc:
        logger.warning("研究规划失败: %s", exc)
        return fallback

    if not data:
        return fallback

    claim = str(data.get("claim") or fallback["claim"]).strip()[:240]
    keywords = [str(k).strip()[:32] for k in (data.get("keywords") or []) if str(k).strip()][:5]
    support_query = _normalize_query(data.get("support_query") or f"{claim} 支持 证据 研究")
    oppose_query = _normalize_query(data.get("oppose_query") or f"{claim} 反例 缺点 风险")
    queries = [support_query, oppose_query]
    if not support_query and oppose_query:
        queries = [oppose_query]
    if support_query and not oppose_query:
        queries = [support_query]
    return {
        "claim": claim or fallback_claim,
        "keywords": keywords,
        "queries": queries,
        "debate_recommended": bool(data.get("debate_recommended")),
    }


def _citations_text(citations: List[Dict[str, Any]]) -> str:
    if not citations:
        return "(无)"
    return "\n".join(
        f"- [笔记#{c.get('note_id')}] {c.get('title')}: {(c.get('snippet') or '')[:180]}"
        for c in citations[:5]
    )


def _local_context(citations: List[Dict[str, Any]]) -> str:
    if not citations:
        return "(没有相关本地笔记)"
    lines = []
    for c in citations[:5]:
        lines.append(
            f"- [笔记#{c.get('note_id')}] {c.get('title')}: "
            f"{(c.get('snippet') or '')[:240]}"
        )
    return "\n".join(lines)


def _build_prompt(
    mode: str,
    claim: str,
    answer: str,
    history_text: str,
    keywords: List[str],
    citations: List[Dict[str, Any]],
    evidence: List[Dict[str, str]],
    search_error: str,
) -> str:
    evidence_text = json.dumps(evidence, ensure_ascii=False, indent=2) if evidence else "(无)"
    warning = ""
    if search_error:
        warning = f"\n搜索过程中出现错误：{search_error}。报告必须明确说明外部证据可能不完整。"
    if mode == "verify":
        return f"""你是知识验证助手。请基于【本地笔记】和【联网搜索摘要】验证一个结论。

【待验证结论】
{claim}

【近期对话】
{history_text or "(无)"}

【分析关键词】
{"、".join(keywords) if keywords else "(无)"}

【原回答片段】
{answer[:2200]}

【本地笔记】
{_local_context(citations)}

【联网搜索摘要】
{evidence_text}{warning}

规则：
1. 只能引用上面给出的来源，不要编造 URL 或结论。
2. 没有外部证据时，明确写“未获得可用联网证据”。
3. 区分来源支持、来源限制、模型推断。

输出 Markdown：
## 搜索分析报告
### 核心观点
### 关键词
### 支持论据
### 反对论据 / 边界条件
### 总结归纳
### 是否建议辩论"""

    return f"""你是知识辩论助手。请基于【本地笔记】和【联网搜索摘要】组织一次简短辩论。

【待辩观点】
{claim}

【近期对话】
{history_text or "(无)"}

【分析关键词】
{"、".join(keywords) if keywords else "(无)"}

【原回答片段】
{answer[:2200]}

【本地笔记】
{_local_context(citations)}

【联网搜索摘要】
{evidence_text}{warning}

规则：
1. 先用近期对话理解真正的争论点，不要重复无关历史。
2. 每一方都要有证据支撑；没有证据时明确写“未获得可用联网证据”。
2. 不要为了让观点成立而忽略反方证据。
3. 结论必须说明适用条件，不要求选出唯一赢家。

输出 Markdown：
## 辩论报告
### 支持方
### 反对方
### 交叉质询
### 裁判结论
### 可复用结论"""


def _fallback_report(
    claim: str,
    evidence: List[Dict[str, str]],
    search_error: str,
    mode: str = "verify",
) -> str:
    lines = ["## 联网报告", "", f"观点：{claim}"]
    if search_error:
        lines.append(f"\n搜索状态：部分失败（{search_error}）")
    elif not evidence:
        lines.append("\n搜索状态：未获得可用联网证据。")
    if evidence:
        lines.append("\n### 找到的资料")
        for item in evidence[:6]:
            lines.append(f"- [{item['title']}]({item['url']})：{item['snippet']}")
        if mode == "debate":
            lines.append("\n### 支持方")
            lines.append("以上来源中与该观点一致的部分需要人工确认。")
            lines.append("\n### 反对方")
            lines.append("以上来源不充分，不能证明该观点在所有条件下成立。")
            lines.append("\n### 可复用结论")
            lines.append("该结论仅在来源覆盖的条件内可用；应继续补充边界条件和反例。")
    else:
        lines.append("\n请稍后重试，或换一个更短的观点再验证。")
    return "\n".join(lines)


def _extract_markdown_section(report: str, headings: tuple[str, ...]) -> str:
    """按标题提取 Markdown 小节，找不到时返回空字符串。"""
    lines = (report or "").splitlines()
    start = -1
    for heading in headings:
        pattern = re.compile(rf"^#{{1,6}}\s*.*{re.escape(heading)}.*$")
        start = next((i for i, line in enumerate(lines) if pattern.match(line.strip())), -1)
        if start != -1:
            break
    if start < 0:
        return ""
    next_start = len(lines)
    for i in range(start + 1, len(lines)):
        if re.match(r"^#{1,6}\s+", lines[i].strip()):
            next_start = i
            break
    return "\n".join(lines[start + 1:next_start]).strip()


def _build_card_draft(
    claim: str,
    report: str,
    citations: List[Dict[str, Any]],
    qa_id: int,
    session_id: Optional[str],
) -> Dict[str, Any]:
    """把辩论结果转成可编辑草稿；不额外调用模型，避免二次消耗。"""
    support = _extract_markdown_section(report, ("支持方",))
    oppose = _extract_markdown_section(report, ("反对方", "反对论据"))
    conclusion = _extract_markdown_section(report, ("可复用结论", "裁判结论"))
    core_summary = "\n\n".join(part for part in (support, oppose) if part) or report[:800]
    card = {
        "title": claim[:60] or "辩论知识卡片",
        "core_summary": core_summary[:800],
        "key_conclusion": (conclusion or report[:600])[:800],
        "application_scenario": "用于复核该结论的适用条件，并提醒自己关注反方证据。",
        "agent_question": "结合这次辩论，你的方法在什么条件下会失败？",
        "source_note_ids": [
            int(item["note_id"]) for item in citations if str(item.get("note_id") or "").isdigit()
        ][:10],
        "qa_id": int(qa_id),
        "session_id": session_id,
    }
    try:
        database.update_qa_card_draft(qa_id, card)
    except Exception:
        logger.warning("辩论卡片草稿写入失败", exc_info=True)
    return card


def research(
    mode: str,
    statement: Optional[str],
    question: Optional[str],
    answer: str,
    citations: List[Dict[str, Any]],
    qa_id: Optional[int] = None,
    session_id: Optional[str] = None,
) -> Dict[str, Any]:
    history_text, history = _history_context(session_id, qa_id)
    client = _get_client()
    plan = _plan_research(client, question or "", answer, history_text, citations)
    claim = (statement or "").strip() or str(plan.get("claim") or "").strip()
    if not claim:
        raise ValueError("缺少可验证的观点")

    keywords = [str(k) for k in (plan.get("keywords") or [])]
    evidence, search_error = _collect_web_evidence([str(q) for q in plan.get("queries") or []])
    report: Optional[str] = None
    if client is not None:
        cfg = get_config()
        prompt = _build_prompt(
            mode, claim, answer, history_text, keywords, citations, evidence, search_error
        )
        try:
            response = client.chat.completions.create(
                model=cfg.QA_MODEL or cfg.LLM_MODEL,
                messages=[{"role": "user", "content": prompt}],
                temperature=0.2,
                max_tokens=2200,
                timeout=120,
            )
            report = (response.choices[0].message.content or "").strip() or None
        except Exception as exc:
            logger.warning("联网 %s 报告生成失败: %s", mode, exc)

    if not report:
        report = _fallback_report(claim, evidence, search_error, mode)

    card_draft: Optional[Dict[str, Any]] = None
    if mode == "debate" and qa_id is not None:
        card_draft = _build_card_draft(claim, report, citations, qa_id, session_id)

    try:
        cfg = get_config()
        database.insert_activity(
            event_type="model",
            message=(
                f"{cfg.QA_MODEL or cfg.LLM_MODEL} 完成{('验证' if mode == 'verify' else '辩论')}报告，"
                f"联网证据 {len(evidence)} 条"
            ),
            model=cfg.QA_MODEL or cfg.LLM_MODEL,
        )
    except Exception:
        logger.debug("联网报告日志写入失败", exc_info=True)

    return {
        "mode": mode,
        "statement": claim,
        "keywords": keywords,
        "debate_recommended": bool(plan.get("debate_recommended")),
        "report": report,
        "sources": evidence,
        "web_evidence_count": len(evidence),
        "history_used_count": len(history),
        "search_note": search_error or None,
        "card_draft": card_draft,
    }

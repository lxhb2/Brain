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
_HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/126.0 Safari/537.36",
    "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
}


def _strip_html(raw: str) -> str:
    text = re.sub(r"<[^>]+>", " ", raw or "")
    return html.unescape(re.sub(r"\s+", " ", text)).strip()


def _search_bing(query: str) -> List[Dict[str, str]]:
    """读取 Bing HTML 结果页，只取标题、链接和摘要。"""
    response = requests.get(
        _BING_URL,
        params={"q": query, "count": 6},
        headers=_HEADERS,
        timeout=12,
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


def _collect_web_evidence(claim: str, mode: str) -> tuple[List[Dict[str, str]], str]:
    if mode == "verify":
        queries = [f"{claim} 证据 研究", f"{claim} 反例 缺点 风险"]
    else:
        queries = [f"{claim} 支持 优点", f"{claim} 反对 缺点 风险"]

    evidence: List[Dict[str, str]] = []
    seen_urls: set[str] = set()
    errors: List[str] = []
    for query in queries:
        try:
            for item in _search_bing(query)[:3]:
                url = item["url"]
                if url in seen_urls:
                    continue
                seen_urls.add(url)
                evidence.append({**item, "query": query})
        except Exception as exc:
            logger.warning("联网搜索失败 query=%s: %s", query, exc)
            errors.append(str(exc))
    return evidence, "; ".join(errors[:2])


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
## 验证报告
### 支持证据
### 反对证据 / 边界条件
### 与我的笔记对照
### 结论
### 下一步验证"""

    return f"""你是知识辩论助手。请基于【本地笔记】和【联网搜索摘要】组织一次简短辩论。

【待辩观点】
{claim}

【原回答片段】
{answer[:2200]}

【本地笔记】
{_local_context(citations)}

【联网搜索摘要】
{evidence_text}{warning}

规则：
1. 每一方都要有证据支撑；没有证据时明确写“未获得可用联网证据”。
2. 不要为了让观点成立而忽略反方证据。
3. 结论必须说明适用条件，不要求选出唯一赢家。

输出 Markdown：
## 辩论报告
### 支持方
### 反对方
### 交叉质询
### 裁判结论
### 下一步实验"""


def _fallback_report(claim: str, evidence: List[Dict[str, str]], search_error: str) -> str:
    lines = ["## 联网报告", "", f"观点：{claim}"]
    if search_error:
        lines.append(f"\n搜索状态：部分失败（{search_error}）")
    elif not evidence:
        lines.append("\n搜索状态：未获得可用联网证据。")
    if evidence:
        lines.append("\n### 找到的资料")
        for item in evidence[:6]:
            lines.append(f"- [{item['title']}]({item['url']})：{item['snippet']}")
    else:
        lines.append("\n请稍后重试，或换一个更短的观点再验证。")
    return "\n".join(lines)


def research(
    mode: str,
    statement: Optional[str],
    question: Optional[str],
    answer: str,
    citations: List[Dict[str, Any]],
) -> Dict[str, Any]:
    claim = (statement or "").strip()
    if not claim:
        claim = (question or "").strip()
    if not claim:
        plain_answer = re.sub(r"#+\s*", "", answer or "")
        claim = plain_answer.strip().replace("\n", " ")[:160]
    if not claim:
        raise ValueError("缺少可验证的观点")

    evidence, search_error = _collect_web_evidence(claim, mode)
    client = _get_client()
    report: Optional[str] = None
    if client is not None:
        cfg = get_config()
        prompt = _build_prompt(mode, claim, answer, citations, evidence, search_error)
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
        report = _fallback_report(claim, evidence, search_error)

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
        "report": report,
        "sources": evidence,
        "web_evidence_count": len(evidence),
        "search_note": search_error or None,
    }

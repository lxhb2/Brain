"""反馈处理薄封装。

submit_feedback: 记录反馈到 feedback 表，并触发 graph_api.apply_feedback
调整被引用笔记之间的链接权重，同时调用 qa_engine.learn_from_feedback
把用户的修正作为长期记忆存入 user_memory（自我成长）。
"""
from __future__ import annotations

import logging
from typing import Optional

import database
import graph_api

logger = logging.getLogger("brain.feedback")


def submit_feedback(
    qa_id: int,
    rating: str,
    correction: Optional[str] = None,
) -> int:
    """提交一次反馈。

    Args:
        qa_id: 关联的问答记录 id
        rating: 'up' 或 'down'
        correction: 可选的修正文本（down 时使用，会被存为长期记忆）

    Returns:
        新建的 feedback.id
    """
    rating = (rating or "").lower().strip()
    if rating not in ("up", "down"):
        raise ValueError("rating 必须是 'up' 或 'down'")

    fb_id = database.insert_feedback(qa_id=qa_id, rating=rating, correction=correction)

    # 根据反馈调整链接权重
    try:
        graph_api.apply_feedback(qa_id, rating)
    except Exception as e:
        logger.warning("反馈触发的权重调整失败 qa_id=%s: %s", qa_id, e)

    # 自我成长：从反馈中提取长期记忆
    try:
        import qa_engine
        qa_engine.learn_from_feedback(qa_id, rating, correction)
    except Exception as e:
        logger.warning("反馈触发的记忆学习失败 qa_id=%s: %s", qa_id, e)

    return fb_id

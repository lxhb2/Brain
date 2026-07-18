"""反馈相关 API 路由。"""
from __future__ import annotations

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

import feedback

router = APIRouter(prefix="/api/feedback", tags=["feedback"])


class FeedbackRequest(BaseModel):
    """反馈请求体。"""

    qa_id: int = Field(..., ge=1)
    rating: str = Field(..., description="'up' 或 'down'")
    correction: str | None = None


@router.post("")
def submit_feedback(req: FeedbackRequest):
    """提交一次反馈，并触发链接权重调整。"""
    if req.rating not in ("up", "down"):
        raise HTTPException(status_code=400, detail="rating 必须是 'up' 或 'down'")
    try:
        fb_id = feedback.submit_feedback(
            qa_id=req.qa_id, rating=req.rating, correction=req.correction
        )
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    return {"feedback_id": fb_id, "qa_id": req.qa_id, "rating": req.rating}

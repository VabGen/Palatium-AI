# src/palatium_ai/presentation/api/routers/feedback.py

"""Router for assistant-message feedback (like/dislike)."""

from __future__ import annotations

from typing import Annotated, Literal

from fastapi import APIRouter, Depends, HTTPException, Request, status
from pydantic import BaseModel, Field

from palatium_ai.domain.feedback.models import FeedbackAction
from palatium_ai.presentation.resources import get_app_resources
from palatium_ai.presentation.security.deps import get_principal
from palatium_ai.presentation.security.principal import AuthPrincipal

router = APIRouter(prefix="/feedback", tags=["feedback"])


class FeedbackRequest(BaseModel):
    """Request body for feedback submission."""

    message_id: str = Field(min_length=1, max_length=128)
    feedback: FeedbackAction
    thread_id: str | None = Field(default=None, max_length=128)
    org_id: str | None = Field(default=None, max_length=128)


class FeedbackResponse(BaseModel):
    """Stored or cleared rating."""

    status: Literal["stored", "cleared", "ok"]
    rating: Literal["like", "dislike"] | None = None


@router.post("")
async def submit_feedback(
    req: FeedbackRequest,
    request: Request,
    principal: Annotated[AuthPrincipal, Depends(get_principal)],
) -> FeedbackResponse:
    """Persist like/dislike (or clear) for the caller's message_id."""
    resources = get_app_resources(request.app)
    if resources.feedback_service is None:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="feedback persistence is not configured",
        )
    org_id = (req.org_id or principal.org_id or "").strip() or None
    result = await resources.feedback_service.submit(
        user_id=principal.subject,
        message_id=req.message_id.strip(),
        action=req.feedback,
        thread_id=(req.thread_id or "").strip() or None,
        org_id=org_id,
    )
    rating = result.feedback.rating if result.feedback is not None else None
    return FeedbackResponse(status=result.status, rating=rating)

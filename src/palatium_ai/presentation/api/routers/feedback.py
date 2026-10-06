# src/palatium_ai/presentation/api/routers/feedback.py

"""Router for feedback."""

from typing import Annotated, Literal

from fastapi import APIRouter, Depends
from pydantic import BaseModel

from palatium_ai.core.logging import logger
from palatium_ai.presentation.security.deps import get_principal
from palatium_ai.presentation.security.principal import AuthPrincipal

router = APIRouter(prefix="/feedback", tags=["feedback"])


class FeedbackRequest(BaseModel):
    """Request body for feedback submission."""

    message_id: str
    feedback: Literal["like", "dislike"]
    org_id: str | None = None


@router.post("")
async def submit_feedback(
    req: FeedbackRequest,
    principal: Annotated[AuthPrincipal, Depends(get_principal)],
) -> dict[str, str]:
    """Submit feedback."""
    logger.info(
        "Feedback received",
        user=principal.subject,
        message_id=req.message_id,
        feedback=req.feedback,
        org=req.org_id or principal.org_id,
    )
    # Feedback is logged but not persisted: like/dislike stops at the log line, so nothing
    # can be aggregated, replayed into evals or attached to a turn by message_id later.
    # TODO(platform/backend, plans/web-embed-assistant §5 п.17, 2026-09-30): store feedback in a table.
    return {"status": "ok"}

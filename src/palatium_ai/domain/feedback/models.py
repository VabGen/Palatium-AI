# src/palatium_ai/domain/feedback/models.py

"""Message feedback aggregate (like/dislike for evals / QA)."""

from __future__ import annotations

from datetime import datetime
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, Field

FeedbackRating = Literal["like", "dislike"]
FeedbackAction = Literal["like", "dislike", "clear"]


class MessageFeedback(BaseModel):
    """One user's rating of an assistant message."""

    model_config = {"frozen": True}

    id: UUID
    user_id: str = Field(min_length=1, max_length=128)
    message_id: str = Field(min_length=1, max_length=128)
    thread_id: str | None = Field(default=None, max_length=128)
    org_id: str | None = Field(default=None, max_length=128)
    rating: FeedbackRating
    created_at: datetime
    updated_at: datetime


class FeedbackUpsertResult(BaseModel):
    """Outcome of submit: stored row or cleared."""

    model_config = {"frozen": True}

    status: Literal["stored", "cleared"]
    feedback: MessageFeedback | None = None

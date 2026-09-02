# src/palatium_ai/domain/sessions/models.py

"""Session persistence records (no ORM)."""

from __future__ import annotations

from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, Field


class SessionRecord(BaseModel):
    """Immutable session snapshot at the application/domain boundary."""

    model_config = {"frozen": True}

    id: UUID
    thread_id: str = Field(min_length=1, max_length=128)
    user_id: str | None = None
    status: str = Field(default="active", min_length=1, max_length=32)
    title: str | None = Field(default=None, max_length=255)
    context: dict[str, object] = Field(default_factory=dict)
    created_at: datetime
    updated_at: datetime

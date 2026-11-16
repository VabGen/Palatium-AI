# src/palatium_ai/domain/projects/models.py

"""Durable project records (Pin / Projects — P2)."""

from __future__ import annotations

from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, Field


class ProjectRecord(BaseModel):
    """Immutable project snapshot at the domain boundary."""

    model_config = {"frozen": True}

    id: UUID
    user_id: str = Field(min_length=1, max_length=128)
    title: str = Field(min_length=1, max_length=255)
    created_at: datetime
    updated_at: datetime

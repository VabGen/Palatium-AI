# src/palatium_ai/domain/memory/promotion.py

"""Medium → long-term graph promotion contracts (060)."""

from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, Field


class PromotionThresholds(BaseModel):
    """Config gates for promote (constants live in MemoryConfig; this is the value object)."""

    model_config = {"frozen": True}

    min_access_frequency: int = Field(default=3, ge=1, le=10_000)
    min_importance: float = Field(default=0.7, ge=0.0, le=1.0)


class PromotionCandidate(BaseModel):
    """One medium-term memory row eligible for graph promotion evaluation."""

    model_config = {"frozen": True}

    namespace: tuple[str, ...]
    entry_key: str = Field(min_length=1, max_length=256)
    text: str = Field(min_length=1, max_length=2000)
    kind: str = Field(default="fact", max_length=32)
    importance: float = Field(default=0.0, ge=0.0, le=1.0)
    access_frequency: int = Field(default=0, ge=0)
    user_id: str = Field(min_length=1, max_length=128)
    confidence: float = Field(default=0.0, ge=0.0, le=1.0)
    contains_pii: bool = False
    last_accessed: datetime | None = None
    promoted_at: datetime | None = None

# src/palatium_ai/domain/memory/compact.py

"""Contracts for ContextBuilder.compact (065) — no silent truncation."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field

CompactMethod = Literal["none", "llm", "extractive"]


class CompactRequest(BaseModel):
    """Dialog + preserved axes for a compact pass."""

    model_config = {"frozen": True}

    dialog: str = Field(default="", max_length=500_000)
    goal: str = Field(default="", max_length=16_000)
    plan: str = Field(default="", max_length=16_000)
    last_results: str = Field(default="", max_length=32_000)
    model_tier: str = Field(default="standard", min_length=1, max_length=64)
    thread_id: str = Field(min_length=1, max_length=128)
    user_id: str | None = Field(default=None, max_length=128)


class CompactResult(BaseModel):
    """Outcome of compact(); preserved fields are never summarized away."""

    model_config = {"frozen": True}

    dialog: str = Field(default="", max_length=500_000)
    goal: str = Field(default="", max_length=16_000)
    plan: str = Field(default="", max_length=16_000)
    last_results: str = Field(default="", max_length=32_000)
    did_compact: bool = False
    method: CompactMethod = "none"
    tokens_before: int = Field(default=0, ge=0)
    tokens_after: int = Field(default=0, ge=0)
    limit_tokens: int = Field(default=0, ge=0)
    persisted_keys: tuple[str, ...] = ()

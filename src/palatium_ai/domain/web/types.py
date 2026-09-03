# src/palatium_ai/domain/web/types.py

"""Web search contracts for ``web_fallback`` (070 last-resort retrieval)."""

from __future__ import annotations

from pydantic import BaseModel, Field


class WebSearchQuery(BaseModel):
    """Parameterized external web search request."""

    model_config = {"frozen": True}

    user_id: str = Field(min_length=1, max_length=128)
    query: str = Field(min_length=1, max_length=500)
    max_results: int = Field(default=5, ge=1, le=10)


class WebSearchHit(BaseModel):
    """One external hit — always treated as untrusted evidence for Critic."""

    model_config = {"frozen": True}

    title: str = Field(default="", max_length=500)
    url: str = Field(default="", max_length=2000)
    snippet: str = Field(default="", max_length=2000)
    score: float = Field(default=0.0, ge=0.0, le=1.0)


class WebSearchResult(BaseModel):
    """Hits returned by ``web_fallback`` (source tagging applied by tool ops)."""

    model_config = {"frozen": True}

    hits: tuple[WebSearchHit, ...] = ()
    hit_count: int = Field(ge=0, default=0)
    provider: str = Field(default="stub", min_length=1, max_length=64)
    note: str = Field(default="", max_length=500)

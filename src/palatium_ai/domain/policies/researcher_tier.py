# src/palatium_ai/domain/policies/researcher_tier.py

"""Researcher model tier by execution strategy (latency, 055).

``reason_only`` (compose / short answers without MCP) uses ``small``.
Retrieval and tool paths keep ``mid`` for harder evidence synthesis.
"""

from __future__ import annotations

from pydantic import BaseModel, Field

from palatium_ai.domain.policies.types import ExecutionStrategy, ModelTier


class ResearcherTierDecision(BaseModel):
    """Outcome of ResearcherTierPolicy for one turn."""

    model_config = {"frozen": True}

    model_tier: ModelTier
    reason: str = Field(min_length=1, max_length=128)


class ResearcherTierPolicy:
    """Pure domain policy: execution strategy → Researcher LLM tier."""

    @classmethod
    def decide(cls, *, strategy: ExecutionStrategy | str | None) -> ResearcherTierDecision:
        name = (strategy or "").strip()
        if name == "reason_only":
            return ResearcherTierDecision(model_tier="small", reason="strategy:reason_only")
        return ResearcherTierDecision(model_tier="mid", reason=f"strategy:{name or 'default'}")

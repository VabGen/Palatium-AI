# src/palatium_ai/domain/policies/retrieval.py

"""Retrieval routing policy — when last-resort tools may bind (055, 070).

``web_fallback`` is allowed only after local knowledge/memory search returned empty.
Binding decision lives in domain policy, not ad-hoc checks inside worker agents.
"""

from __future__ import annotations

from pydantic import BaseModel, Field

# Platform tools that must never auto-bind from capability discovery (070).
LAST_RESORT_PLATFORM_TOOLS: frozenset[str] = frozenset({"web_fallback"})


class RetrievalBindingDecision(BaseModel):
    """Outcome of RetrievalPolicy for one tool binding attempt."""

    model_config = {"frozen": True}

    allowed: bool
    reason: str = Field(min_length=1, max_length=128)


class RetrievalPolicy:
    """Pure domain policy for retrieval tool eligibility."""

    @staticmethod
    def may_bind_tool(*, tool_name: str, local_retrieval_empty: bool) -> RetrievalBindingDecision:
        """Return whether a platform tool may be selected for this turn."""
        if tool_name not in LAST_RESORT_PLATFORM_TOOLS:
            return RetrievalBindingDecision(allowed=True, reason="not_last_resort")
        if local_retrieval_empty:
            return RetrievalBindingDecision(allowed=True, reason="local_retrieval_empty")
        return RetrievalBindingDecision(allowed=False, reason="web_fallback_requires_empty_local")

    @staticmethod
    def is_last_resort_tool(tool_name: str) -> bool:
        return tool_name in LAST_RESORT_PLATFORM_TOOLS

# src/palatium_ai/domain/policies/hop_budget.py

"""Soft degradation when turn hop budget is exceeded (latency P1.10, 055).

Pure policy: no I/O. Critic skips LLM judge; Formatter skips repair loops.
Fail-open on missing timings (no collector → no degrade).
"""

from __future__ import annotations

from pydantic import BaseModel, Field


class HopBudgetDecision(BaseModel):
    """Outcome of HopBudgetPolicy for one gate."""

    model_config = {"frozen": True}

    degrade: bool
    reason: str = Field(min_length=1, max_length=128)


class HopBudgetPolicy:
    """Pure domain policy: hop total vs budget → soft degrade actions."""

    @classmethod
    def should_skip_critic_llm(
        cls,
        *,
        hop_total_ms: int,
        budget_ms: int,
    ) -> HopBudgetDecision:
        """Skip Critic LLM when the turn is already over budget."""
        if budget_ms <= 0:
            return HopBudgetDecision(degrade=False, reason="budget_disabled")
        if hop_total_ms > budget_ms:
            return HopBudgetDecision(degrade=True, reason="hop_budget_exceeded")
        return HopBudgetDecision(degrade=False, reason="within_budget")

    @classmethod
    def should_skip_formatter_repairs(
        cls,
        *,
        hop_total_ms: int,
        budget_ms: int,
    ) -> HopBudgetDecision:
        """Skip Formatter schema/locale repair LLM loops when over budget."""
        if budget_ms <= 0:
            return HopBudgetDecision(degrade=False, reason="budget_disabled")
        if hop_total_ms > budget_ms:
            return HopBudgetDecision(degrade=True, reason="hop_budget_exceeded")
        return HopBudgetDecision(degrade=False, reason="within_budget")

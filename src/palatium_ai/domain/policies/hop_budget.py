# src/palatium_ai/domain/policies/hop_budget.py

"""Soft degradation when turn hop budget is exceeded (latency, 055).

Pure policy: no I/O. Soft-degrade drops *optional* quality work first:
Critic LLM judge and Formatter schema/locale repair loops.

Presentation Formatter LLM is never gated here — skipping it flattens brand UI
when attachment analysis lands near the budget (live 2026-10-08). Fail-open when
timings are missing (no collector → no degrade).

Per-strategy scales shrink the effective budget for low-risk routes so soft
degrade kicks in earlier (format_only should not burn a full knowledge budget).
"""

from __future__ import annotations

from pydantic import BaseModel, Field

# Multipliers vs the configured turn_hop_budget_ms (ObservabilityConfig).
_STRATEGY_BUDGET_SCALE: dict[str, float] = {
    "format_only": 0.6,
    "clarify": 0.5,
    "ack_only": 0.4,
}


class HopBudgetDecision(BaseModel):
    """Outcome of HopBudgetPolicy for one gate."""

    model_config = {"frozen": True}

    degrade: bool
    reason: str = Field(min_length=1, max_length=128)


class HopBudgetPolicy:
    """Pure domain policy: hop total vs budget → soft degrade actions."""

    @classmethod
    def effective_budget_ms(cls, *, base_ms: int, strategy: str | None) -> int:
        """Scale the turn hop budget for the selected execution strategy."""
        if base_ms <= 0:
            return 0
        scale = _STRATEGY_BUDGET_SCALE.get((strategy or "").strip(), 1.0)
        return max(1_000, int(base_ms * scale))

    @classmethod
    def should_skip_critic_llm(
        cls,
        *,
        hop_total_ms: int,
        budget_ms: int,
    ) -> HopBudgetDecision:
        """Skip Critic LLM when the turn is already over budget."""
        return cls._exceeded(hop_total_ms=hop_total_ms, budget_ms=budget_ms)

    @classmethod
    def should_skip_formatter_repairs(
        cls,
        *,
        hop_total_ms: int,
        budget_ms: int,
    ) -> HopBudgetDecision:
        """Skip Formatter schema/locale repair LLM loops when over budget."""
        return cls._exceeded(hop_total_ms=hop_total_ms, budget_ms=budget_ms)

    @staticmethod
    def _exceeded(*, hop_total_ms: int, budget_ms: int) -> HopBudgetDecision:
        if budget_ms <= 0:
            return HopBudgetDecision(degrade=False, reason="budget_disabled")
        if hop_total_ms > budget_ms:
            return HopBudgetDecision(degrade=True, reason="hop_budget_exceeded")
        return HopBudgetDecision(degrade=False, reason="within_budget")

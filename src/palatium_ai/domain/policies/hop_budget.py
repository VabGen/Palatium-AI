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
#
# Down-scales: low-risk routes must degrade earlier — a restyle should not burn a
# full knowledge budget.
#
# Up-scales: a worker pass is structurally more expensive than a chat turn. It costs
# continuation + intent + weaving + supervisor + worker + critic + formatter — seven
# graph hops, each with an LLM call. Measured against a single 15 s number, such a
# turn is over budget *by construction*, so the alert fired on every legitimate
# research request and stopped being a signal. The scale is not a free pass: the
# comparison excludes external I/O (document parse/OCR), so what remains inside the
# scaled budget is genuine agent work.
_STRATEGY_BUDGET_SCALE: dict[str, float] = {
    "format_only": 0.6,
    "clarify": 0.5,
    "ack_only": 0.4,
    "reason_only": 1.6,
    "retrieve_then_reason": 2.0,
    "direct_tool_call": 2.0,
    "code_sandbox": 2.0,
    "data_analysis": 2.0,
}

# Critic LLM is optional quality work. When workers already burned most of the
# turn budget, skip Critic early so Formatter (never gated) keeps headroom.
_CRITIC_SOFT_DEGRADE_RATIO = 0.7


class HopBudgetDecision(BaseModel):
    """Outcome of HopBudgetPolicy for one gate."""

    model_config = {"frozen": True}

    degrade: bool
    reason: str = Field(min_length=1, max_length=128)


class HopBudgetPolicy:
    """Pure domain policy: agent work vs budget → soft degrade actions.

    Every gate compares **agent work**, not wall clock: a turn that spent 25 s in
    OCR of two scans has no reason to skip the Critic or the Formatter repairs —
    the agents themselves were fast (see ``HopTimingCollector.agent_ms``).
    """

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
        """Skip Critic LLM when over budget or soft headroom for Formatter is gone."""
        hard = cls._exceeded(hop_total_ms=hop_total_ms, budget_ms=budget_ms)
        if hard.degrade or hard.reason == "budget_disabled":
            return hard
        soft_limit = int(budget_ms * _CRITIC_SOFT_DEGRADE_RATIO)
        if hop_total_ms > soft_limit:
            return HopBudgetDecision(degrade=True, reason="hop_budget_protect_formatter")
        return hard

    @classmethod
    def should_skip_formatter_repairs(
        cls,
        *,
        hop_total_ms: int,
        budget_ms: int,
    ) -> HopBudgetDecision:
        """Skip Formatter schema/locale repair LLM loops when over budget."""
        return cls._exceeded(hop_total_ms=hop_total_ms, budget_ms=budget_ms)

    @classmethod
    def should_skip_last_resort_retrieval(
        cls,
        *,
        hop_total_ms: int,
        budget_ms: int,
    ) -> HopBudgetDecision:
        """Skip ``web_fallback`` when the turn is already over budget (070 last-resort)."""
        return cls._exceeded(hop_total_ms=hop_total_ms, budget_ms=budget_ms)

    @staticmethod
    def _exceeded(*, hop_total_ms: int, budget_ms: int) -> HopBudgetDecision:
        if budget_ms <= 0:
            return HopBudgetDecision(degrade=False, reason="budget_disabled")
        if hop_total_ms > budget_ms:
            return HopBudgetDecision(degrade=True, reason="hop_budget_exceeded")
        return HopBudgetDecision(degrade=False, reason="within_budget")

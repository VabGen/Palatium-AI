"""HopBudgetPolicy — soft degrade when turn budget exceeded."""

from __future__ import annotations

from palatium_ai.domain.policies import HopBudgetPolicy


def test_within_budget_no_degrade() -> None:
    decision = HopBudgetPolicy.should_skip_critic_llm(hop_total_ms=1_000, budget_ms=15_000)
    assert decision.degrade is False


def test_exceeded_skips_critic() -> None:
    decision = HopBudgetPolicy.should_skip_critic_llm(hop_total_ms=16_000, budget_ms=15_000)
    assert decision.degrade is True
    assert decision.reason == "hop_budget_exceeded"


def test_exceeded_skips_formatter_repairs() -> None:
    decision = HopBudgetPolicy.should_skip_formatter_repairs(hop_total_ms=20_000, budget_ms=15_000)
    assert decision.degrade is True


def test_disabled_budget() -> None:
    decision = HopBudgetPolicy.should_skip_critic_llm(hop_total_ms=99_000, budget_ms=0)
    assert decision.degrade is False
    assert decision.reason == "budget_disabled"


def test_format_only_budget_is_tighter() -> None:
    full = HopBudgetPolicy.effective_budget_ms(base_ms=15_000, strategy="retrieve_then_reason")
    fmt = HopBudgetPolicy.effective_budget_ms(base_ms=15_000, strategy="format_only")
    assert full == 15_000
    assert fmt == 9_000


def test_apply_strategy_budget_on_collector() -> None:
    from palatium_ai.core.observability.hop_timings import HopTimingCollector

    hop = HopTimingCollector(budget_ms=15_000, base_budget_ms=15_000)
    hop.apply_strategy_budget("format_only")
    assert hop.budget_ms == 9_000
    hop.apply_strategy_budget("retrieve_then_reason")
    assert hop.budget_ms == 15_000

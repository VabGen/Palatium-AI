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


def test_critic_soft_degrade_protects_formatter_headroom() -> None:
    """At 70% of budget, Critic yields remaining time to Formatter."""
    decision = HopBudgetPolicy.should_skip_critic_llm(hop_total_ms=11_000, budget_ms=15_000)
    assert decision.degrade is True
    assert decision.reason == "hop_budget_protect_formatter"
    still_ok = HopBudgetPolicy.should_skip_critic_llm(hop_total_ms=10_000, budget_ms=15_000)
    assert still_ok.degrade is False


def test_exceeded_skips_formatter_repairs() -> None:
    decision = HopBudgetPolicy.should_skip_formatter_repairs(hop_total_ms=20_000, budget_ms=15_000)
    assert decision.degrade is True


def test_exceeded_skips_last_resort_retrieval() -> None:
    decision = HopBudgetPolicy.should_skip_last_resort_retrieval(
        hop_total_ms=16_000,
        budget_ms=15_000,
    )
    assert decision.degrade is True
    assert decision.reason == "hop_budget_exceeded"


def test_disabled_budget() -> None:
    decision = HopBudgetPolicy.should_skip_critic_llm(hop_total_ms=99_000, budget_ms=0)
    assert decision.degrade is False
    assert decision.reason == "budget_disabled"


def test_worker_budget_scales_above_chat_budget() -> None:
    """A worker pass costs ~7 hops, so one chat budget would alert by construction.

    The scale is not a free pass: the comparison already excludes external I/O
    (OCR/parse), so the scaled budget governs genuine agent work only.
    """
    chat = HopBudgetPolicy.effective_budget_ms(base_ms=15_000, strategy="format_only")
    worker = HopBudgetPolicy.effective_budget_ms(base_ms=15_000, strategy="retrieve_then_reason")
    assert chat == 9_000
    assert worker == 30_000
    assert worker > chat


def test_apply_strategy_budget_on_collector() -> None:
    from palatium_ai.core.observability.hop_timings import HopTimingCollector

    hop = HopTimingCollector(budget_ms=15_000, base_budget_ms=15_000)
    hop.apply_strategy_budget("format_only", scaler=HopBudgetPolicy.effective_budget_ms)
    assert hop.budget_ms == 9_000
    hop.apply_strategy_budget("retrieve_then_reason", scaler=HopBudgetPolicy.effective_budget_ms)
    assert hop.budget_ms == 30_000


def test_external_io_is_not_agent_work() -> None:
    """A 25 s OCR must not read as a slow graph (nor trigger soft degrade)."""
    from palatium_ai.core.observability.hop_timings import HopTimingCollector

    hop = HopTimingCollector(budget_ms=15_000, base_budget_ms=15_000)
    hop.record(node="researcher", agent="researcher", duration_ms=27_000)
    hop.record_external_io(kind="attachment_parse", duration_ms=25_000)

    assert hop.total_ms() == 27_000
    assert hop.io_ms() == 25_000
    assert hop.agent_ms() == 2_000

    status = hop.budget_status()
    assert status["hop_budget_exceeded"] is False
    assert status["hop_wall_over_budget"] is True
    assert status["hop_io_ms"] == 25_000
    assert (
        HopBudgetPolicy.should_skip_critic_llm(
            hop_total_ms=hop.agent_ms(),
            budget_ms=hop.budget_ms,
        ).degrade
        is False
    )


def test_agent_work_over_budget_still_alerts() -> None:
    """Excluding I/O must not hide a genuine agent regression."""
    from palatium_ai.core.observability.hop_timings import HopTimingCollector

    hop = HopTimingCollector(budget_ms=15_000, base_budget_ms=15_000)
    hop.record(node="researcher", agent="researcher", duration_ms=40_000)
    hop.record_external_io(kind="attachment_parse", duration_ms=5_000)

    status = hop.budget_status()
    assert status["hop_budget_exceeded"] is True
    assert status["hop_wall_over_budget"] is False
    assert status["hop_agent_ms"] == 35_000

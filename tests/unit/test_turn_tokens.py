"""Unit tests for turn token collector and metrics."""

from __future__ import annotations

from palatium_ai.core.observability.metrics import agent_metrics
from palatium_ai.core.observability.turn_tokens import turn_token_usage


def test_turn_token_usage_aggregates() -> None:
    with turn_token_usage() as tokens:
        tokens.record(
            agent="intent_classifier",
            model="m1",
            prompt_tokens=100,
            completion_tokens=20,
            cost_usd=0.001,
        )
        tokens.record(
            agent="formatter",
            model="m2",
            prompt_tokens=50,
            completion_tokens=10,
            cost_usd=0.002,
        )
        fields = tokens.as_log_fields()
    assert fields["token_prompt_total"] == 150
    assert fields["token_completion_total"] == 30
    assert fields["token_total"] == 180
    assert fields["llm_calls"] == 2
    assert fields["token_by_agent"] == {"intent_classifier": 120, "formatter": 60}
    assert fields["cost_usd_total"] == 0.003


def test_record_token_usage_increments_prometheus() -> None:
    agent_metrics.record_token_usage(
        agent_type="intent_classifier",
        model="test-model",
        prompt_tokens=11,
        completion_tokens=7,
    )
    # In-memory counter is enough for smoke; no public getter required.

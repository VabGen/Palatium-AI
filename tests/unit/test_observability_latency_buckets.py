"""Custom Adaptive Grounding latency histogram buckets must stay pinned."""

from __future__ import annotations

from palatium_ai.core.observability.metrics import GROUNDING_LATENCY_BUCKETS, agent_metrics


def test_grounding_latency_buckets_contract() -> None:
    assert GROUNDING_LATENCY_BUCKETS == (0.1, 0.25, 0.5, 1.0, 2.0, 5.0, 10.0, 20.0, 40.0, 60.0)
    assert agent_metrics.grounding_latency_buckets() == GROUNDING_LATENCY_BUCKETS

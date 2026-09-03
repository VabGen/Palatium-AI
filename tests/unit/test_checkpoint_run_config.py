"""Unit tests for checkpointer run config and msgpack allowlist serde."""

from __future__ import annotations

import logging

import pytest

from palatium_ai.application.orchestration.run_config import build_graph_run_config
from palatium_ai.core.observability.hop_timings import turn_hop_timings
from palatium_ai.core.types.graph_nodes import (
    NODE_CONTEXT_ENRICHER_CONTINUATION,
    NODE_CONTEXT_ENRICHER_WEAVING,
)
from palatium_ai.domain.agents.intent import IntentClassifierOutput, IntentTaskResult
from palatium_ai.infrastructure.memory.checkpoint_serde import (
    CHECKPOINT_MSGPACK_ALLOWLIST,
    build_checkpoint_serde,
    migrate_graph_checkpoint,
)


def test_graph_run_config_splits_thread_and_task() -> None:
    config = build_graph_run_config(thread_id="conv-1", task_id="task-9")
    assert config["configurable"]["thread_id"] == "conv-1"
    assert config["configurable"]["checkpoint_ns"] == "task-9"
    assert config["recursion_limit"] == 32


def test_graph_run_config_rejects_empty_ids() -> None:
    with pytest.raises(ValueError):
        build_graph_run_config(thread_id=" ", task_id="t1")
    with pytest.raises(ValueError):
        build_graph_run_config(thread_id="t1", task_id="")


def test_checkpoint_allowlist_covers_core_graph_types() -> None:
    names = {item[1] for item in CHECKPOINT_MSGPACK_ALLOWLIST}
    for required in (
        "IntentTaskResult",
        "DialogTurnWindow",
        "ContextPacket",
        "ContentDocument",
        "EffectiveRoutingIntent",
    ):
        assert required in names


def test_checkpoint_serde_roundtrips_intent_without_unregistered_warning(
    caplog: pytest.LogCaptureFixture,
) -> None:
    """Explicit allowlist must revive IntentTaskResult without msgpack warnings."""
    serde = build_checkpoint_serde()
    result = IntentTaskResult(
        task_id="t1",
        agent_role="intent_classifier",
        status="success",
        confidence=0.9,
        requires_review=False,
        output=IntentClassifierOutput(
            task_kind="social_conversation",
            requires_mcp=False,
            candidate_capabilities=(),
            confidence=0.9,
            reasoning="phatic",
        ),
    )
    with caplog.at_level(logging.WARNING, logger="langgraph.checkpoint.serde.jsonplus"):
        typed, payload = serde.dumps_typed(result)
        restored = serde.loads_typed((typed, payload))
    assert isinstance(restored, IntentTaskResult)
    assert restored.task_id == "t1"
    assert restored.output is not None
    assert restored.output.task_kind == "social_conversation"
    assert not any("msgpack_unregistered" in r.getMessage() for r in caplog.records)
    assert not any("Add to allowed_msgpack_modules" in r.getMessage() for r in caplog.records)


def test_migrate_graph_checkpoint_remaps_legacy_node_ids() -> None:
    payload = {
        "next": ("contextualizer", "context_weaver"),
        "nested": {"tasks": [{"node": "context_weaver"}]},
    }
    migrated = migrate_graph_checkpoint(payload)
    assert migrated["next"] == (NODE_CONTEXT_ENRICHER_CONTINUATION, NODE_CONTEXT_ENRICHER_WEAVING)
    assert migrated["nested"]["tasks"][0]["node"] == NODE_CONTEXT_ENRICHER_WEAVING


def test_migrating_serde_roundtrips_channel_values_and_remaps_legacy_nodes() -> None:
    """Full serde load path must migrate legacy node ids inside nested checkpoint payloads."""
    serde = build_checkpoint_serde()
    result = IntentTaskResult(
        task_id="t-legacy",
        agent_role="intent_classifier",
        status="success",
        confidence=0.9,
        requires_review=False,
        output=IntentClassifierOutput(
            task_kind="knowledge_request",
            requires_mcp=True,
            candidate_capabilities=(),
            confidence=0.9,
            reasoning="eval",
        ),
    )
    payload = {
        "next": ("contextualizer", "context_weaver"),
        "channel_values": {"classification": result},
    }
    typed, raw = serde.dumps_typed(payload)
    restored = serde.loads_typed((typed, raw))
    assert isinstance(restored, dict)
    assert restored["next"] == (NODE_CONTEXT_ENRICHER_CONTINUATION, NODE_CONTEXT_ENRICHER_WEAVING)
    channel = restored.get("channel_values")
    assert isinstance(channel, dict)
    classification = channel.get("classification")
    assert isinstance(classification, IntentTaskResult)
    assert classification.task_id == "t-legacy"


def test_turn_hop_timings_collects_and_resets() -> None:
    with turn_hop_timings() as hops:
        hops.record(node="intent_classifier", agent="intent_classifier", duration_ms=12, status="success")
        hops.record(node="formatter", agent="formatter", duration_ms=40, status="success")
        fields = hops.as_log_fields()
    assert fields["hop_count"] == 2
    assert fields["hop_total_ms"] == 52
    assert fields["hop_ms"] == {"intent_classifier": 12, "formatter": 40}


def test_turn_hop_budget_status_flags_exceeded() -> None:
    with turn_hop_timings() as hops:
        hops.record(node="contextualizer", agent="contextualizer", duration_ms=9000, status="success")
        hops.record(node="formatter", agent="formatter", duration_ms=8000, status="success")
        status = hops.budget_status(15_000)
    assert status["hop_budget_exceeded"] is True
    assert status["hop_slowest_node"] == "contextualizer"
    assert status["hop_slowest_ms"] == 9000

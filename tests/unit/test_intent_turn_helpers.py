# tests/unit/test_intent_turn_helpers.py

"""Implicit per-turn extract admission at the enqueue call site (060, 080)."""

from __future__ import annotations

from types import SimpleNamespace
from typing import Any, cast
from uuid import uuid4

import pytest

from palatium_ai.application.orchestration.state import AgentGraphState
from palatium_ai.application.services.intent_turn_helpers import (
    enqueue_turn_extract,
    resolved_turn_kind,
)
from palatium_ai.core.observability.metrics import agent_metrics
from palatium_ai.domain.agents.intent import IntentClassifierOutput, IntentTaskResult


class _RecordingConsolidation:
    def __init__(self) -> None:
        self.calls: list[dict[str, str | None]] = []

    async def enqueue(
        self,
        *,
        thread_id: str,
        task_id: str,
        user_id: str | None = None,
        org_id: str | None = None,
    ) -> str:
        self.calls.append({"thread_id": thread_id, "task_id": task_id, "user_id": user_id, "org_id": org_id})
        return "queued"


def _state(task_kind: str) -> AgentGraphState:
    return cast("AgentGraphState", {"routing_intent": SimpleNamespace(task_kind=task_kind)})


@pytest.mark.asyncio()
async def test_social_turn_does_not_enqueue_extract() -> None:
    """A phatic turn must not buy a MemoryKeeper LLM call (the observed cost driver)."""
    consolidation = _RecordingConsolidation()
    before = agent_metrics.memory_extract_skipped_count("task_kind:social_conversation")

    reason = await enqueue_turn_extract(
        consolidation,
        _state("social_conversation"),
        thread_id="thread-1",
        task_id=str(uuid4()),
        user_id="user-1",
        org_id="org-1",
    )

    assert reason == "task_kind:social_conversation"
    assert consolidation.calls == []
    assert agent_metrics.memory_extract_skipped_count("task_kind:social_conversation") == before + 1


@pytest.mark.asyncio()
async def test_substantive_turn_enqueues_once() -> None:
    consolidation = _RecordingConsolidation()
    task_id = str(uuid4())

    reason = await enqueue_turn_extract(
        consolidation,
        _state("knowledge_request"),
        thread_id="thread-2",
        task_id=task_id,
        user_id="user-2",
        org_id=None,
    )

    assert reason == "admitted"
    assert consolidation.calls == [
        {"thread_id": "thread-2", "task_id": task_id, "user_id": "user-2", "org_id": None},
    ]


@pytest.mark.asyncio()
async def test_missing_consolidation_is_not_an_error() -> None:
    reason = await enqueue_turn_extract(
        None,
        _state("knowledge_request"),
        thread_id="thread-3",
        task_id=str(uuid4()),
        user_id=None,
        org_id=None,
    )

    assert reason == "disabled"


def test_resolved_turn_kind_prefers_routing_intent_then_classification() -> None:
    routed = cast("AgentGraphState", {"routing_intent": SimpleNamespace(task_kind="tool_execution")})
    assert resolved_turn_kind(routed) == "tool_execution"

    classified = cast(
        "AgentGraphState",
        {
            "classification": IntentTaskResult(
                task_id=str(uuid4()),
                agent_role="intent_classifier",
                status="success",
                confidence=0.9,
                output=IntentClassifierOutput(
                    task_kind="knowledge_request",
                    requires_mcp=False,
                    confidence=0.9,
                    reasoning="test",
                ),
            )
        },
    )
    assert resolved_turn_kind(classified) == "knowledge_request"


def test_resolved_turn_kind_defaults_to_clarification() -> None:
    """A turn that never reached classification cannot be recalled as a fact."""
    empty: dict[str, Any] = {}
    assert resolved_turn_kind(cast("AgentGraphState", empty)) == "clarification_needed"

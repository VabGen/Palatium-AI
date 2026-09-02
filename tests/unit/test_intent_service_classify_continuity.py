"""IntentService.classify must surface ContinuityPolicy routing axes, not raw Intent."""

from __future__ import annotations

from typing import Any

import pytest

from palatium_ai.application.services.intent_service import IntentService
from palatium_ai.domain.agents.intent import IntentClassifierOutput, IntentTaskResult
from palatium_ai.domain.memory.continuity import EffectiveRoutingIntent


class _FakeSessionService:
    def __init__(self) -> None:
        self.patches: list[dict[str, Any]] = []

    async def touch_session(self, **kwargs: object) -> None:
        patch = kwargs.get("context_patch")
        if isinstance(patch, dict):
            self.patches.append(patch)

    async def assert_thread_access(self, **_kwargs: object) -> None:
        return None


class _FakeHitlService:
    pass


class _FakeGraph:
    def __init__(self, state: dict[str, object]) -> None:
        self._state = state

    async def ainvoke(self, _input: object, config: object | None = None) -> dict[str, object]:
        _ = config
        return self._state


@pytest.mark.asyncio
async def test_classify_overlays_routing_intent_axes() -> None:
    raw = IntentTaskResult(
        task_id="t1",
        agent_role="intent_classifier",
        status="partial",
        confidence=0.4,
        requires_review=True,
        output=IntentClassifierOutput(
            task_kind="clarification_needed",
            requires_mcp=False,
            requires_user_choice=False,
            underspecification_kind="open_text",
            candidate_capabilities=(),
            confidence=0.4,
            reasoning="history-blind clarify",
        ),
    )
    routing = EffectiveRoutingIntent(
        task_kind="knowledge_request",
        requires_mcp=False,
        requires_user_choice=False,
        underspecification_kind="none",
        candidate_capabilities=("summarize",),
        continuation_kind="answer",
        prior_context="prior answer text",
        suppress_intent_hitl=True,
        trust_prior_for_workers=True,
        reasoning="continuity remapped clarify→knowledge",
    )
    sessions = _FakeSessionService()
    service = IntentService(
        _FakeGraph({"classification": raw, "routing_intent": routing}),  # type: ignore[arg-type]
        session_service=sessions,  # type: ignore[arg-type]
        hitl_service=_FakeHitlService(),  # type: ignore[arg-type]
    )

    result = await service.classify(text="and what about X?", thread_id="th-1", task_id="t1")

    assert result.output is not None
    assert result.output.task_kind == "knowledge_request"
    assert result.output.candidate_capabilities == ("summarize",)
    assert result.requires_review is False
    assert result.status == "success"
    assert sessions.patches[-1]["last_task_kind"] == "knowledge_request"
    assert sessions.patches[-1]["requires_mcp"] is False

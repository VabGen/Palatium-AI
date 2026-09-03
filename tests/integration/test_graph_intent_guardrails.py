# tests/integration/test_graph_intent_guardrails.py

"""Integration: Intent + Contextualizer nodes through Harness guardrails (fake LLM)."""

from __future__ import annotations

import pytest

from palatium_ai.application.agents.harness import Harness
from palatium_ai.application.agents.intent_classifier import INTENT_CLASSIFIER_CONFIG, IntentClassifierAgent
from palatium_ai.application.orchestration.graph import build_agent_graph
from palatium_ai.application.services.hitl_service import HitlService
from palatium_ai.application.services.intent_service import IntentService
from palatium_ai.infrastructure.hitl.memory_store import InMemoryHitlCardStore
from tests.conftest import (
    FakeDialogTurnStore,
    FakeLLMPort,
    SequentialFakeLLMPort,
    make_analyst_agent,
    make_coder_agent,
    make_continuation_agent,
    make_critic_agent,
    make_dual_agent_stack,
    make_formatter_agent,
    make_graph_checkpointer,
    make_intent_stack,
    make_researcher_agent,
    make_supervisor_agent,
    make_weaving_agent,
)

_HITL_HMAC = "integration-test-hitl-hmac-key-32b"  # noqa: S105


class _FakeSessionService:
    async def touch_session(self, **_kwargs: object) -> None:
        return None

    async def assert_thread_access(self, **_kwargs: object) -> None:
        return None


def _formatter_json(title: str) -> str:
    import json

    return json.dumps(
        {
            "schema_version": 1,
            "locale": "en-US",
            "title": title,
            "blocks": [{"type": "paragraph", "text": title}],
            "actions": [],
            "meta": {"confidence": 0.95, "requires_review": False, "source_refs": []},
        }
    )


@pytest.mark.integration
@pytest.mark.asyncio
async def test_graph_intent_classifier_via_harness_guardrails() -> None:
    """End-to-end classify path: contextualizer pass-through → intent BaseAgent."""
    intent_json = (
        '{"task_kind": "knowledge_request", "requires_mcp": false, '
        '"candidate_capabilities": ["summarize"], "confidence": 0.93, "reasoning": "integration"}'
    )
    harness, intent_agent = make_intent_stack(FakeLLMPort(intent_json))
    continuation = make_continuation_agent(harness=harness)
    graph = build_agent_graph(
        harness=harness,
        continuation_agent=continuation,
        intent_agent=intent_agent,
        supervisor_agent=make_supervisor_agent(harness),
        weaving_agent=make_weaving_agent(harness=harness),
        researcher_agent=make_researcher_agent(
            FakeLLMPort('{"summary": "x", "confidence": 0.9, "sources_used": []}'), harness=harness
        ),
        coder_agent=make_coder_agent(harness=harness),
        analyst_agent=make_analyst_agent(harness=harness),
        critic_agent=make_critic_agent(
            FakeLLMPort('{"accuracy_score": 9, "safety_score": 9, "requires_review": false, "summary": "ok"}')
        ),
        formatter_agent=make_formatter_agent(FakeLLMPort(_formatter_json("Answer"))),
        checkpointer=make_graph_checkpointer(),
    )
    service = IntentService(
        graph,  # type: ignore[arg-type]
        session_service=_FakeSessionService(),  # type: ignore[arg-type]
        hitl_service=HitlService(InMemoryHitlCardStore(), signing_secret=_HITL_HMAC),
    )

    result = await service.classify(text="What is Palatium?", thread_id="integration-1", task_id="task-int-1")

    assert result.status == "success"
    assert result.output is not None
    assert result.output.task_kind == "knowledge_request"


@pytest.mark.integration
@pytest.mark.asyncio
async def test_graph_process_full_pipeline_fake_llm() -> None:
    """Integration smoke: full graph process() with migrated guardrail nodes."""
    intent_json = (
        '{"task_kind": "knowledge_request", "requires_mcp": false, '
        '"candidate_capabilities": [], "confidence": 0.95, "reasoning": "integration process"}'
    )
    harness, intent_agent = make_intent_stack(FakeLLMPort(intent_json))
    continuation = make_continuation_agent(harness=harness)
    graph = build_agent_graph(
        harness=harness,
        continuation_agent=continuation,
        intent_agent=intent_agent,
        supervisor_agent=make_supervisor_agent(harness),
        weaving_agent=make_weaving_agent(harness=harness),
        researcher_agent=make_researcher_agent(
            FakeLLMPort('{"summary": "Palatium is an agent platform.", "confidence": 0.94, "sources_used": []}'),
            harness=harness,
        ),
        coder_agent=make_coder_agent(harness=harness),
        analyst_agent=make_analyst_agent(harness=harness),
        critic_agent=make_critic_agent(
            FakeLLMPort('{"accuracy_score": 9, "safety_score": 9, "requires_review": false, "summary": "ok"}')
        ),
        formatter_agent=make_formatter_agent(FakeLLMPort(_formatter_json("Palatium overview"))),
        checkpointer=make_graph_checkpointer(),
    )
    service = IntentService(
        graph,  # type: ignore[arg-type]
        session_service=_FakeSessionService(),  # type: ignore[arg-type]
        hitl_service=HitlService(InMemoryHitlCardStore(), signing_secret=_HITL_HMAC),
    )

    result = await service.process(text="Tell me about Palatium", thread_id="integration-process-1")

    assert result.status == "success"
    assert result.output is not None
    assert result.output.title == "Palatium overview"


@pytest.mark.integration
@pytest.mark.asyncio
async def test_graph_social_phatic_skips_researcher() -> None:
    """Social greeting: ack_only route → critic passthrough → formatter (no researcher LLM)."""
    intent_json = (
        '{"task_kind": "social_conversation", "requires_mcp": false, '
        '"candidate_capabilities": [], "confidence": 0.96, "reasoning": "greeting"}'
    )
    llm = SequentialFakeLLMPort([intent_json, _formatter_json("Hello")])
    harness = Harness(llm=llm)
    intent_agent = IntentClassifierAgent(harness, INTENT_CLASSIFIER_CONFIG)
    unused_researcher = FakeLLMPort('{"summary": "must-not-run", "confidence": 0.1, "sources_used": []}')
    graph = build_agent_graph(
        harness=harness,
        continuation_agent=make_continuation_agent(harness=harness),
        intent_agent=intent_agent,
        supervisor_agent=make_supervisor_agent(harness),
        weaving_agent=make_weaving_agent(harness=harness),
        researcher_agent=make_researcher_agent(unused_researcher, harness=harness),
        coder_agent=make_coder_agent(harness=harness),
        analyst_agent=make_analyst_agent(harness=harness),
        critic_agent=make_critic_agent(FakeLLMPort("should-not-be-called")),
        formatter_agent=make_formatter_agent(llm, harness=harness),
        checkpointer=make_graph_checkpointer(),
    )
    service = IntentService(
        graph,  # type: ignore[arg-type]
        session_service=_FakeSessionService(),  # type: ignore[arg-type]
        hitl_service=HitlService(InMemoryHitlCardStore(), signing_secret=_HITL_HMAC),
    )

    result = await service.process(text="hello", thread_id="integration-social-1")

    assert result.status == "success"
    assert result.output is not None
    assert result.output.title == "Hello"
    assert len(unused_researcher.calls) == 0


@pytest.mark.integration
@pytest.mark.asyncio
async def test_graph_format_followup_with_dialog_memory() -> None:
    """Format follow-up rewrites via continuation + routes to formatter without researcher."""
    dialog = FakeDialogTurnStore()
    await dialog.append_turn(thread_id="integration-format-1", role="user", content="Составь план встречи")
    await dialog.append_turn(
        thread_id="integration-format-1",
        role="assistant",
        content="План встречи:\n1. Цель\n2. Повестка",
    )

    harness, continuation, intent_agent, pipeline_llm = make_dual_agent_stack(
        """{
          "rewritten_query": "Представь предыдущий план встречи в виде таблицы",
          "continuation_kind": "format",
          "confidence": 0.92,
          "refers_to_prior": true,
          "prior_assistant_excerpt": "План встречи",
          "reasoning": "format follow-up"
        }""",
        '{"task_kind": "response_formatting", "requires_mcp": false, '
        '"candidate_capabilities": ["format"], "confidence": 0.9, "reasoning": "format"}',
    )
    unused_researcher = FakeLLMPort('{"summary": "unused", "confidence": 0.1, "sources_used": []}')
    graph = build_agent_graph(
        harness=harness,
        continuation_agent=continuation,
        intent_agent=intent_agent,
        supervisor_agent=make_supervisor_agent(harness),
        weaving_agent=make_weaving_agent(harness=harness),
        researcher_agent=make_researcher_agent(unused_researcher, harness=harness),
        coder_agent=make_coder_agent(harness=harness),
        analyst_agent=make_analyst_agent(harness=harness),
        critic_agent=make_critic_agent(FakeLLMPort("should-not-be-called")),
        formatter_agent=make_formatter_agent(
            FakeLLMPort(_formatter_json("Meeting plan table")),
            harness=harness,
        ),
        checkpointer=make_graph_checkpointer(),
    )
    service = IntentService(
        graph,  # type: ignore[arg-type]
        session_service=_FakeSessionService(),  # type: ignore[arg-type]
        hitl_service=HitlService(InMemoryHitlCardStore(), signing_secret=_HITL_HMAC),
        dialog_turn_store=dialog,  # type: ignore[arg-type]
    )

    result = await service.process(text="дай в виде таблицы", thread_id="integration-format-1")

    assert result.status == "success"
    assert result.output is not None
    assert "table" in result.output.title.lower() or "meeting" in result.output.title.lower()
    assert len(unused_researcher.calls) == 0
    assert pipeline_llm._index == 2

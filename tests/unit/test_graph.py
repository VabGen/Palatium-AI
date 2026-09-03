# tests/unit/test_graph.py

"""Тесты LangGraph пайплайна."""

from __future__ import annotations

import json

import pytest

from palatium_ai.application.agents.context_enricher import CONTEXTUALIZER_CONFIG, ContextualizerAgent
from palatium_ai.application.agents.harness import Harness
from palatium_ai.application.agents.intent_classifier import INTENT_CLASSIFIER_CONFIG, IntentClassifierAgent
from palatium_ai.application.orchestration.graph import build_agent_graph
from palatium_ai.application.services.intent_service import IntentService
from palatium_ai.domain.content import HeadingBlock
from tests.conftest import (
    FakeLLMPort,
    FakeMCPRegistry,
    SequentialFakeLLMPort,
    make_critic_agent,
    make_formatter_agent,
    make_graph_checkpointer,
    make_researcher_agent,
    make_supervisor_agent,
    make_weaving_agent,
)

_HITL_HMAC = "unit-test-hitl-hmac-key-32b"  # noqa: S105


class _FakeSessionService:
    """No-op session persistence for graph unit tests."""

    async def touch_session(self, **_kwargs: object) -> None:
        return None

    async def assert_thread_access(self, **_kwargs: object) -> None:
        return None


def _intent_service(graph: object) -> IntentService:
    from palatium_ai.application.services.hitl_service import HitlService
    from palatium_ai.infrastructure.hitl.memory_store import InMemoryHitlCardStore

    return IntentService(
        graph,  # type: ignore[arg-type]
        session_service=_FakeSessionService(),  # type: ignore[arg-type]
        hitl_service=HitlService(InMemoryHitlCardStore(), signing_secret=_HITL_HMAC),
    )


def _graph(**kwargs: object) -> object:
    """build_agent_graph with a no-op continuation LLM (empty history → pass-through)."""
    from tests.conftest import make_analyst_agent, make_coder_agent

    continuation = kwargs.pop("continuation_agent", None)
    harness = kwargs.get("harness")
    if continuation is None:
        if harness is None:
            harness = Harness(llm=FakeLLMPort("{}"))
            kwargs["harness"] = harness
        continuation = ContextualizerAgent(harness, CONTEXTUALIZER_CONFIG)  # type: ignore[arg-type]
    if "coder_agent" not in kwargs:
        kwargs["coder_agent"] = make_coder_agent(harness=harness)  # type: ignore[arg-type]
    if "analyst_agent" not in kwargs:
        kwargs["analyst_agent"] = make_analyst_agent(harness=harness)  # type: ignore[arg-type]
    return build_agent_graph(
        continuation_agent=continuation,
        checkpointer=make_graph_checkpointer(),
        **kwargs,
    )  # type: ignore[arg-type]


def _formatter_document_json(title: str, *, locale: str = "en-US") -> str:
    return json.dumps(
        {
            "schema_version": 1,
            "locale": locale,
            "title": title,
            "blocks": [
                {"type": "heading", "level": 2, "text": title, "icon": None},
                {"type": "paragraph", "text": title},
            ],
            "actions": [],
            "meta": {
                "confidence": 0.95,
                "requires_review": False,
                "source_refs": [],
            },
        },
        ensure_ascii=False,
    )


def _intent_stack(llm_intent: FakeLLMPort) -> tuple[Harness, IntentClassifierAgent]:
    harness = Harness(llm=llm_intent)
    return harness, IntentClassifierAgent(harness, INTENT_CLASSIFIER_CONFIG)


@pytest.mark.asyncio
async def test_graph_classifies_intent_end_to_end() -> None:
    llm_intent = FakeLLMPort(
        '{"task_kind": "multi_step_workflow", "requires_mcp": true, "candidate_capabilities": ["orchestrate","tool_call"], "confidence": 0.88, "reasoning": "Requires multiple steps"}',
    )

    llm_researcher = FakeLLMPort(
        '{"summary": "Prepared response", "confidence": 0.91, "sources_used": ["llm_internal_reasoning"]}',
    )

    llm_critic = FakeLLMPort(
        '{"accuracy_score": 9, "safety_score": 9, "requires_review": false, "summary": "Looks correct"}',
    )
    llm_formatter = FakeLLMPort(_formatter_document_json("Final formatted answer"))

    harness, agent = _intent_stack(llm_intent)
    researcher = make_researcher_agent(llm_researcher, harness=harness)
    critic = make_critic_agent(llm_critic)
    formatter = make_formatter_agent(llm_formatter)
    supervisor = make_supervisor_agent(harness)
    graph = _graph(
        harness=harness,
        intent_agent=agent,
        supervisor_agent=supervisor,
        weaving_agent=make_weaving_agent(harness=harness),
        researcher_agent=researcher,
        critic_agent=critic,
        formatter_agent=formatter,
    )
    service = _intent_service(graph)

    result = await service.classify(
        text="Schedule a meeting with the team tomorrow",
        thread_id="thread-graph-1",
        task_id="task-graph-1",
    )

    assert result.status == "success"
    assert result.output is not None
    assert result.output.task_kind == "multi_step_workflow"
    assert result.task_id == "task-graph-1"


@pytest.mark.asyncio
async def test_graph_records_node_metrics() -> None:
    llm_intent = FakeLLMPort(
        '{"task_kind": "knowledge_request", "requires_mcp": false, "candidate_capabilities": ["summarize"], "confidence": 0.95, "reasoning": "General chat"}',
    )

    llm_researcher = FakeLLMPort(
        '{"summary": "Helpful answer", "confidence": 0.96, "sources_used": ["llm_internal_reasoning"]}',
    )

    llm_critic = FakeLLMPort(
        '{"accuracy_score": 9, "safety_score": 9, "requires_review": false, "summary": "Looks correct"}',
    )
    llm_formatter = FakeLLMPort(_formatter_document_json("Formatted answer"))

    harness, agent = _intent_stack(llm_intent)
    researcher = make_researcher_agent(llm_researcher, harness=harness)
    critic = make_critic_agent(llm_critic)
    formatter = make_formatter_agent(llm_formatter)
    supervisor = make_supervisor_agent(harness)
    service = _intent_service(
        _graph(
            harness=harness,
            intent_agent=agent,
            supervisor_agent=supervisor,
            weaving_agent=make_weaving_agent(harness=harness),
            researcher_agent=researcher,
            critic_agent=critic,
            formatter_agent=formatter,
        )
    )

    await service.classify(text="How are you?", thread_id="m1")

    from palatium_ai.core.observability.metrics import agent_metrics

    assert agent_metrics.node_execution_count("intent_classifier", "intent_classifier_node") >= 1
    assert agent_metrics.node_execution_count("researcher", "researcher_node") >= 1
    assert agent_metrics.node_execution_count("formatter", "formatter_node") >= 1


@pytest.mark.asyncio
async def test_graph_skips_researcher_for_non_research_route() -> None:
    llm_intent = FakeLLMPort(
        '{"task_kind": "response_formatting", "requires_mcp": false, "candidate_capabilities": ["format"], "confidence": 0.9, "reasoning": "Formatting request"}',
    )
    llm_researcher = FakeLLMPort(
        '{"summary": "Should not be used", "confidence": 0.2, "sources_used": []}',
    )
    llm_critic = FakeLLMPort(
        '{"accuracy_score": 9, "safety_score": 9, "requires_review": false, "summary": "Looks correct"}',
    )
    llm_formatter = FakeLLMPort(_formatter_document_json("Formatted-only answer"))

    harness, intent_agent = _intent_stack(llm_intent)
    service = _intent_service(
        _graph(
            harness=harness,
            intent_agent=intent_agent,
            supervisor_agent=make_supervisor_agent(harness),
            weaving_agent=make_weaving_agent(harness=harness),
            researcher_agent=make_researcher_agent(llm_researcher, harness=harness),
            critic_agent=make_critic_agent(llm_critic),
            formatter_agent=make_formatter_agent(llm_formatter),
        )
    )

    result = await service.classify(text="Schedule a meeting tomorrow", thread_id="route-skip")

    assert result.output is not None
    assert result.output.task_kind == "response_formatting"
    assert len(llm_researcher.calls) == 0


@pytest.mark.asyncio
async def test_graph_social_skips_researcher_and_critic_llm() -> None:
    llm_intent = FakeLLMPort(
        '{"task_kind": "social_conversation", "requires_mcp": false, '
        '"candidate_capabilities": [], "confidence": 0.96, "reasoning": "Greeting"}',
    )
    llm_researcher = FakeLLMPort(
        '{"summary": "Should not run", "confidence": 0.1, "sources_used": []}',
    )
    llm_critic = FakeLLMPort(
        '{"accuracy_score": 1, "safety_score": 1, "requires_review": true, "summary": "should not run"}',
    )
    llm_formatter = FakeLLMPort(_formatter_document_json("Привет!", locale="ru-RU"))

    harness, intent_agent = _intent_stack(llm_intent)
    service = _intent_service(
        _graph(
            harness=harness,
            intent_agent=intent_agent,
            supervisor_agent=make_supervisor_agent(harness),
            weaving_agent=make_weaving_agent(harness=harness),
            researcher_agent=make_researcher_agent(llm_researcher, harness=harness),
            critic_agent=make_critic_agent(llm_critic),
            formatter_agent=make_formatter_agent(llm_formatter),
        )
    )

    result = await service.classify(text="привет", thread_id="social-1")

    assert result.output is not None
    assert result.output.task_kind == "social_conversation"
    assert len(llm_researcher.calls) == 0
    assert len(llm_critic.calls) == 0
    assert len(llm_formatter.calls) == 1


@pytest.mark.asyncio
async def test_process_returns_formatter_result() -> None:
    harness, intent_agent = _intent_stack(
        FakeLLMPort(
            '{"task_kind": "knowledge_request", "requires_mcp": false, "candidate_capabilities": ["summarize"], "confidence": 0.94, "reasoning": "Answer request"}',
        )
    )
    service = _intent_service(
        _graph(
            harness=harness,
            intent_agent=intent_agent,
            supervisor_agent=make_supervisor_agent(harness),
            weaving_agent=make_weaving_agent(harness=harness),
            researcher_agent=make_researcher_agent(
                FakeLLMPort(
                    '{"summary": "Draft answer", "confidence": 0.93, "sources_used": ["llm_internal_reasoning"]}',
                ),
                harness=harness,
            ),
            critic_agent=make_critic_agent(
                FakeLLMPort(
                    '{"accuracy_score": 9, "safety_score": 9, "requires_review": false, "summary": "Ready"}',
                )
            ),
            formatter_agent=make_formatter_agent(
                FakeLLMPort(_formatter_document_json("Final user answer")),
            ),
        )
    )

    result = await service.process(text="Explain this system", thread_id="process-1")

    assert result.status == "success"
    assert result.output is not None
    assert result.output.title == "Final user answer"
    assert isinstance(result.output.blocks[0], HeadingBlock)


@pytest.mark.asyncio
async def test_researcher_uses_mcp_registry_when_required() -> None:
    mcp_registry = FakeMCPRegistry()
    harness, intent_agent = _intent_stack(
        FakeLLMPort(
            '{"task_kind": "tool_execution", "requires_mcp": true, "candidate_capabilities": ["search"], "confidence": 0.97, "reasoning": "Need MCP search"}',
        )
    )
    service = _intent_service(
        _graph(
            harness=harness,
            intent_agent=intent_agent,
            supervisor_agent=make_supervisor_agent(harness),
            weaving_agent=make_weaving_agent(mcp_registry, harness=harness),
            researcher_agent=make_researcher_agent(
                SequentialFakeLLMPort(
                    ['{"query": "Find the contract in EDMS"}'],
                ),
                mcp_registry,
                harness=harness,
            ),
            critic_agent=make_critic_agent(
                FakeLLMPort(
                    '{"accuracy_score": 9, "safety_score": 9, "requires_review": false, "summary": "Ready"}',
                )
            ),
            formatter_agent=make_formatter_agent(
                FakeLLMPort(_formatter_document_json("Formatted MCP answer")),
            ),
        )
    )

    result = await service.process(text="Find the contract in EDMS", thread_id="mcp-path-1")

    assert result.status == "success"
    assert len(mcp_registry.calls) == 1
    server_name, tool_call = mcp_registry.calls[0]
    assert server_name == "edms"
    assert tool_call.name == "search_documents"

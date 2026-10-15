"""Graph smoke: empty MCP + adaptive ON → degrade, no nothing-found stub."""

from __future__ import annotations

import json

import pytest

from palatium_ai.application.agents.context_enricher import CONTEXTUALIZER_CONFIG, ContextualizerAgent
from palatium_ai.application.agents.evals.cassette import (
    _ResearcherEvalMcpRegistry,
    load_cassette_response,
)
from palatium_ai.application.agents.harness import Harness
from palatium_ai.application.agents.intent_classifier import INTENT_CLASSIFIER_CONFIG, IntentClassifierAgent
from palatium_ai.application.orchestration.agent_registry import GraphAgents
from palatium_ai.application.orchestration.graph import build_agent_graph
from palatium_ai.application.services.intent_service import IntentService
from palatium_ai.domain.mcp.models import MCPToolCall, MCPToolResult
from tests.conftest import (
    SequentialFakeLLMPort,
    make_analyst_agent,
    make_coder_agent,
    make_critic_agent,
    make_formatter_agent,
    make_graph_checkpointer,
    make_researcher_agent,
    make_supervisor_agent,
    make_weaving_agent,
)

_HITL_HMAC = "unit-test-hitl-hmac-key-32b"
_NOTHING_FOUND = "ничего не найдено"


class _FakeSessionService:
    async def touch_session(self, **_kwargs: object) -> None:
        return None

    async def assert_thread_access(self, **_kwargs: object) -> None:
        return None

    async def get_session(self, **_kwargs: object) -> None:
        return None


class _EmptySearchRegistry(_ResearcherEvalMcpRegistry):
    """platform.search_knowledge always returns hit_count=0."""

    async def call_tool(
        self,
        server_name: str,
        tool_call: MCPToolCall,
        *,
        allow_unpinned: bool = False,
    ) -> MCPToolResult:
        _ = allow_unpinned
        self.calls.append((server_name, tool_call))
        return MCPToolResult(
            content=[{"type": "text", "text": json.dumps({"hit_count": 0, "hits": []})}],
            is_error=False,
        )


def _formatter_document_json(title: str) -> str:
    return json.dumps(
        {
            "schema_version": 1,
            "locale": "ru-RU",
            "title": title,
            "blocks": [
                {"type": "heading", "level": 2, "text": title, "icon": None},
                {"type": "paragraph", "text": title},
            ],
            "actions": [],
            "meta": {"confidence": 0.95, "requires_review": False, "source_refs": []},
        },
        ensure_ascii=False,
    )


@pytest.mark.asyncio()
async def test_graph_empty_mcp_optional_degrades_not_stub(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("ADAPTIVE_GROUNDING_ENABLED", "true")
    monkeypatch.setenv("ADAPTIVE_GROUNDING_ROLLOUT_PCT", "100")
    from palatium_ai.core.config import get_settings

    get_settings.cache_clear()
    try:
        intent_json = (
            '{"task_kind":"knowledge_request","requires_mcp":false,'
            '"candidate_capabilities":["analyze"],"grounding":"optional",'
            '"grounding_reason":"general analysis","confidence":0.93,'
            '"reasoning":"compare clouds"}'
        )
        degrade_json = json.dumps(
            {
                "summary": "Облако гибче по opex; коробка — capex и контроль.",
                "confidence": 0.88,
                "sources_used": ["llm_ungrounded"],
            },
            ensure_ascii=False,
        )
        critic_json = '{"accuracy_score": 8, "safety_score": 9, "requires_review": false, "summary": "ok"}'
        mcp = _EmptySearchRegistry()
        # Shared sequence: Intent → tool-args → degrade LLM → Critic → Formatter.
        # Args builder uses researcher._llm; degrade uses harness.call_llm — same port.
        shared_llm = SequentialFakeLLMPort(
            [
                intent_json,
                load_cassette_response("researcher/search_knowledge_args.json"),
                degrade_json,
                critic_json,
                _formatter_document_json("Облако vs коробка"),
            ],
        )
        harness = Harness(llm=shared_llm)
        intent_agent = IntentClassifierAgent(harness, INTENT_CLASSIFIER_CONFIG)
        graph = build_agent_graph(
            GraphAgents(
                continuation_agent=ContextualizerAgent(harness, CONTEXTUALIZER_CONFIG),
                intent_agent=intent_agent,
                supervisor_agent=make_supervisor_agent(harness),
                weaving_agent=make_weaving_agent(mcp, harness=harness),
                researcher_agent=make_researcher_agent(shared_llm, mcp, harness=harness),
                coder_agent=make_coder_agent(harness=harness),
                analyst_agent=make_analyst_agent(harness=harness),
                critic_agent=make_critic_agent(shared_llm),
                formatter_agent=make_formatter_agent(shared_llm),
            ),
            harness=harness,
            checkpointer=make_graph_checkpointer(),
        )
        from palatium_ai.application.services.hitl_service import HitlService
        from palatium_ai.infrastructure.hitl.memory_store import InMemoryHitlCardStore

        service = IntentService(
            graph,  # type: ignore[arg-type]
            session_service=_FakeSessionService(),  # type: ignore[arg-type]
            hitl_service=HitlService(InMemoryHitlCardStore(), signing_secret=_HITL_HMAC),
        )
        ask = "Сравни подписку на облачный сервис и покупку коробочного ПО. Проанализируй ситуацию: продажи упали на 15%."
        result = await service.process(
            text=ask,
            thread_id="adaptive-empty-1",
            user_id="eval-user",
        )

        assert result.output is not None
        plain = result.output.plain_text()
        assert _NOTHING_FOUND not in plain.lower()
        assert "Не удалось получить данные" not in plain
        assert "Облако" in plain or "короб" in plain.lower() or "Облако" in (result.output.title or "")
        assert any(call.name == "search_knowledge" for _srv, call in mcp.calls)
        assert len(shared_llm.calls) >= 3
    finally:
        get_settings.cache_clear()

# tests/conftest.py

"""Общие фикстуры для тестов."""

from __future__ import annotations

from collections.abc import AsyncIterator
from datetime import UTC, datetime
from uuid import uuid4

import pytest

from palatium_ai.domain.agents.agent_config import AgentConfig
from palatium_ai.domain.llm.models import (
    ChatMessage,
    LLMCompletion,
    LLMResponseFormat,
    LLMStreamDelta,
)
from palatium_ai.domain.mcp.external_schemas import EDMS_SEARCH_DOCUMENTS_SCHEMA
from palatium_ai.domain.mcp.models import MCPToolCall, MCPToolDescriptor, MCPToolResult, MCPToolSummary
from palatium_ai.domain.memory.turns import DialogTurn, DialogTurnWindow


class PlatformKnowledgeMcpRegistry:
    """Minimal MCPRegistryPort for in-process platform tools."""

    def __init__(self, handler: object) -> None:
        self._handler = handler

    async def call_tool(self, server_name: str, call: MCPToolCall) -> MCPToolResult:
        if server_name != "platform":
            msg = f"unexpected MCP server: {server_name}"
            raise ValueError(msg)
        return await self._handler.call_tool(call.name, call.arguments)  # type: ignore[union-attr]


def make_platform_mcp_registry(
    *,
    memory_port: object | None = None,
    knowledge_port: object | None = None,
    consolidation: object | None = None,
) -> PlatformKnowledgeMcpRegistry:
    from palatium_ai.infrastructure.knowledge.in_memory_knowledge_port import InMemoryKnowledgePort
    from palatium_ai.infrastructure.mcp.platform_tool_handler import PlatformToolHandler
    from palatium_ai.infrastructure.memory.in_memory_store import InMemoryMemoryPort

    handler = PlatformToolHandler(
        knowledge_port=knowledge_port or InMemoryKnowledgePort(),  # type: ignore[arg-type]
        memory_port=memory_port or InMemoryMemoryPort(),  # type: ignore[arg-type]
        consolidation=consolidation,  # type: ignore[arg-type]
    )
    return PlatformKnowledgeMcpRegistry(handler)


def make_document_ingest_stack(
    knowledge_port: object | None = None,
) -> tuple[object, object, object, object]:
    """DocumentIngestService + HitlService + KnowledgePort + PlatformToolHandler."""
    from palatium_ai.application.agents.harness import Harness
    from palatium_ai.application.agents.text_ingestor import TEXT_INGESTOR_CONFIG, TextIngestorAgent
    from palatium_ai.application.services.document_ingest_service import DocumentIngestService
    from palatium_ai.application.services.hitl_service import HitlService
    from palatium_ai.infrastructure.hitl.memory_store import InMemoryHitlCardStore
    from palatium_ai.infrastructure.knowledge.in_memory_knowledge_port import InMemoryKnowledgePort
    from palatium_ai.infrastructure.mcp.platform_tool_handler import PlatformToolHandler

    resolved_knowledge = knowledge_port or InMemoryKnowledgePort()
    handler = PlatformToolHandler(knowledge_port=resolved_knowledge)  # type: ignore[arg-type]
    harness = Harness(llm=FakeLLMPort("{}"))
    hitl = HitlService(InMemoryHitlCardStore(), signing_secret="unit-test-hitl-hmac-key-32bytes!!")
    ingest = DocumentIngestService(
        harness=harness,
        text_ingestor=TextIngestorAgent(harness, TEXT_INGESTOR_CONFIG),
        hitl_service=hitl,
        mcp_registry=PlatformKnowledgeMcpRegistry(handler),
    )
    return ingest, resolved_knowledge, hitl, handler


def make_memory_hitl_stack() -> tuple[object, object, object, object, object]:
    """MemorySaveService + MemoryForgetService + HitlService + MemoryPort + handler."""
    from palatium_ai.application.services.hitl_service import HitlService
    from palatium_ai.application.services.memory_forget_service import MemoryForgetService
    from palatium_ai.application.services.memory_save_service import MemorySaveService
    from palatium_ai.infrastructure.hitl.memory_store import InMemoryHitlCardStore
    from palatium_ai.infrastructure.knowledge.in_memory_knowledge_port import InMemoryKnowledgePort
    from palatium_ai.infrastructure.mcp.platform_tool_handler import PlatformToolHandler
    from palatium_ai.infrastructure.memory.in_memory_store import InMemoryMemoryPort

    port = InMemoryMemoryPort()
    handler = PlatformToolHandler(knowledge_port=InMemoryKnowledgePort(), memory_port=port)
    registry = PlatformKnowledgeMcpRegistry(handler)
    hitl = HitlService(InMemoryHitlCardStore(), signing_secret="unit-test-hitl-hmac-key-32bytes!!")
    save = MemorySaveService(hitl_service=hitl, mcp_registry=registry)
    forget = MemoryForgetService(hitl_service=hitl, mcp_registry=registry)
    return save, forget, port, hitl, handler


def make_memory_consolidate_hitl_stack(
    *,
    llm_content: str,
    dialog_turns: list[tuple[str, str]] | None = None,
) -> tuple[object, object, object, object, object, object]:
    """MemoryConsolidateService + consolidation worker + HITL + port + handler + dialog."""
    from datetime import UTC, datetime
    from uuid import uuid4

    from palatium_ai.application.agents.harness import Harness
    from palatium_ai.application.agents.memory_keeper import MEMORY_KEEPER_CONFIG, MemoryKeeperAgent
    from palatium_ai.application.services.hitl_service import HitlService
    from palatium_ai.application.services.memory_consolidate_service import MemoryConsolidateService
    from palatium_ai.application.services.memory_consolidation import MemoryConsolidationService
    from palatium_ai.application.services.memory_fact_persistence import MemoryFactPersistenceService
    from palatium_ai.domain.memory.turns import DialogTurn, DialogTurnWindow
    from palatium_ai.infrastructure.hitl.memory_store import InMemoryHitlCardStore
    from palatium_ai.infrastructure.knowledge.in_memory_knowledge_port import InMemoryKnowledgePort
    from palatium_ai.infrastructure.mcp.platform_tool_handler import PlatformToolHandler
    from palatium_ai.infrastructure.memory.in_memory_store import InMemoryMemoryPort

    class _DialogStore:
        def __init__(self, turns: list[tuple[str, str]]) -> None:
            self._turns = turns

        async def append_turn(self, **_kwargs: object) -> DialogTurn:
            raise NotImplementedError

        async def list_recent_turns(self, *, thread_id: str, limit: int = 12) -> DialogTurnWindow:
            items = tuple(
                DialogTurn(
                    id=uuid4(),
                    thread_id=thread_id,
                    role=role,  # type: ignore[arg-type]
                    content=content,
                    seq=idx,
                    created_at=datetime.now(UTC),
                )
                for idx, (role, content) in enumerate(self._turns[:limit])
            )
            return DialogTurnWindow(thread_id=thread_id, turns=items, limit=limit)

    port = InMemoryMemoryPort()
    handler = PlatformToolHandler(knowledge_port=InMemoryKnowledgePort(), memory_port=port)
    registry = PlatformKnowledgeMcpRegistry(handler)
    harness = Harness(llm=FakeLLMPort(llm_content))
    keeper = MemoryKeeperAgent(harness, MEMORY_KEEPER_CONFIG)
    dialog = _DialogStore(
        dialog_turns
        or [
            ("user", "Составь план встречи"),
            ("assistant", "1. Цель 2. Повестка"),
            ("user", "Дай в виде таблицы"),
        ]
    )
    consolidation = MemoryConsolidationService(
        harness=harness,
        memory_keeper=keeper,
        memory_port=port,
        memory_persistence=MemoryFactPersistenceService(registry),
        dialog_turn_store=dialog,  # type: ignore[arg-type]
    )
    handler._consolidation = consolidation  # late-bind for MCP consolidate_memory
    hitl = HitlService(InMemoryHitlCardStore(), signing_secret="unit-test-hitl-hmac-key-32bytes!!")
    consolidate = MemoryConsolidateService(hitl_service=hitl, mcp_registry=registry)
    return consolidate, consolidation, port, hitl, handler, dialog


class FakeLLMPort:
    """In-memory LLMPort для unit-тестов."""

    def __init__(self, content: str, *, model: str = "test-model") -> None:
        self._content = content
        self._model = model
        self.calls: list[list[ChatMessage]] = []

    async def generate(
        self,
        messages: list[ChatMessage],
        *,
        model: str | None = None,
        temperature: float | None = None,
        max_tokens: int | None = None,
        response_format: LLMResponseFormat | None = None,
    ) -> LLMCompletion:
        _ = temperature, max_tokens, response_format
        self.calls.append(messages)
        return LLMCompletion(content=self._content, model=model or self._model)

    async def generate_stream(
        self,
        messages: list[ChatMessage],
        *,
        model: str | None = None,
        temperature: float | None = None,
        max_tokens: int | None = None,
        response_format: LLMResponseFormat | None = None,
    ) -> AsyncIterator[LLMStreamDelta]:
        _ = temperature, max_tokens, response_format
        self.calls.append(messages)
        yield LLMStreamDelta(content=self._content)


class SequentialFakeLLMPort:
    """LLMPort, который отдаёт ответы по очереди."""

    def __init__(self, responses: list[str], *, model: str = "test-model") -> None:
        self._responses = responses
        self._model = model
        self.calls: list[list[ChatMessage]] = []
        self._index = 0

    async def generate(
        self,
        messages: list[ChatMessage],
        *,
        model: str | None = None,
        temperature: float | None = None,
        max_tokens: int | None = None,
        response_format: LLMResponseFormat | None = None,
    ) -> LLMCompletion:
        _ = temperature, max_tokens, response_format
        self.calls.append(messages)
        if self._index >= len(self._responses):
            raise RuntimeError("SequentialFakeLLMPort has no more responses")
        content = self._responses[self._index]
        self._index += 1
        return LLMCompletion(content=content, model=model or self._model)

    async def generate_stream(
        self,
        messages: list[ChatMessage],
        *,
        model: str | None = None,
        temperature: float | None = None,
        max_tokens: int | None = None,
        response_format: LLMResponseFormat | None = None,
    ) -> AsyncIterator[LLMStreamDelta]:
        completion = await self.generate(
            messages,
            model=model,
            temperature=temperature,
            max_tokens=max_tokens,
            response_format=response_format,
        )
        yield LLMStreamDelta(content=completion.content)


class FakeDialogTurnStore:
    """In-memory dialog turns for integration/follow-up tests."""

    def __init__(self) -> None:
        self._turns: dict[str, list[DialogTurn]] = {}

    async def append_turn(
        self,
        *,
        thread_id: str,
        role: str,
        content: str,
        task_id: str | None = None,
        payload: object | None = None,
    ) -> DialogTurn:
        _ = payload
        seq = len(self._turns.get(thread_id, []))
        turn = DialogTurn(
            id=uuid4(),
            thread_id=thread_id,
            role=role,  # type: ignore[arg-type]
            content=content,
            task_id=task_id,
            seq=seq,
            created_at=datetime.now(UTC),
        )
        self._turns.setdefault(thread_id, []).append(turn)
        return turn

    async def list_recent_turns(self, *, thread_id: str, limit: int = 12) -> DialogTurnWindow:
        items = self._turns.get(thread_id, [])[-limit:]
        return DialogTurnWindow(thread_id=thread_id, turns=tuple(items), limit=limit)


class FakeMCPRegistry:
    """In-memory MCP registry for unit-tests."""

    def __init__(self) -> None:
        self.calls: list[tuple[str, MCPToolCall]] = []
        self._tools = {
            "edms": [
                MCPToolDescriptor(
                    name="search_documents",
                    description="Search EDMS documents by query string.",
                    inputSchema=EDMS_SEARCH_DOCUMENTS_SCHEMA,
                    annotations={"readOnlyHint": True},
                )
            ]
        }

    def list_servers(self) -> list[str]:
        """Возвращает список серверов."""
        return list(self._tools.keys())

    async def list_tools(self, server_name: str, *, force_refresh: bool = False) -> list[MCPToolDescriptor]:
        """Возвращает tools указанного тестового сервера."""
        _ = force_refresh
        return self._tools[server_name]

    async def list_tool_summaries(self, server_name: str, *, force_refresh: bool = False) -> list[MCPToolSummary]:
        """Progressive disclosure summaries for capability discovery."""
        tools = await self.list_tools(server_name, force_refresh=force_refresh)
        return [tool.to_summary() for tool in tools]

    async def get_tool(self, server_name: str, tool_name: str) -> MCPToolDescriptor | None:
        """Return one full descriptor by name."""
        tools = await self.list_tools(server_name)
        return next((tool for tool in tools if tool.name == tool_name), None)

    async def call_tool(self, server_name: str, tool_call: MCPToolCall) -> MCPToolResult:
        """Запоминает вызов и возвращает stub content."""
        self.calls.append((server_name, tool_call))
        return MCPToolResult(
            content=[{"type": "text", "text": f"Stub MCP result for {tool_call.arguments.get('query', '')}"}],
            isError=False,
        )


@pytest.fixture
def sample_agent_config() -> AgentConfig:
    """AgentConfig с одним разрешённым инструментом."""
    return AgentConfig(
        name="test_worker",
        role="analyst",
        model_tier="small",
        temperature=0.0,
        allowed_tools=("search",),
        timeout_seconds=5,
        max_retries=1,
        confidence_threshold=0.7,
    )


def make_graph_checkpointer():
    """Checkpoint saver with platform serde (tests may import infrastructure)."""
    from langgraph.checkpoint.memory import MemorySaver

    from palatium_ai.infrastructure.memory.checkpoint_serde import build_checkpoint_serde

    return MemorySaver(serde=build_checkpoint_serde())


def make_intent_stack(llm: FakeLLMPort) -> tuple[object, object]:
    """Harness + IntentClassifierAgent for graph/unit tests."""
    from palatium_ai.application.agents.harness import Harness
    from palatium_ai.application.agents.intent_classifier import INTENT_CLASSIFIER_CONFIG, IntentClassifierAgent

    harness = Harness(llm=llm)
    return harness, IntentClassifierAgent(harness, INTENT_CLASSIFIER_CONFIG)


async def run_contextualizer(llm: FakeLLMPort | SequentialFakeLLMPort, task_input: object):
    """Harness path for Contextualizer unit/eval tests."""
    from palatium_ai.application.agents.context_enricher import CONTEXTUALIZER_CONFIG, ContextualizerAgent
    from palatium_ai.application.agents.harness import Harness
    from palatium_ai.application.orchestration.agent_bridge import (
        contextualizer_output_to_task_result,
        contextualizer_to_agent_input,
    )

    harness = Harness(llm=llm)  # type: ignore[arg-type]
    agent = ContextualizerAgent(harness, CONTEXTUALIZER_CONFIG)
    agent_input = contextualizer_to_agent_input(
        task_input,  # type: ignore[arg-type]
        trace_id="trace-eval",
        thread_id=task_input.dialog_window.thread_id,  # type: ignore[union-attr]
    )
    output = await harness.execute_with_guardrails(agent, agent_input)
    return contextualizer_output_to_task_result(
        output,
        task_id=task_input.task_id,  # type: ignore[arg-type]
        agent_role=agent.config.role,
    )


async def run_supervisor(task_input: object):
    """Harness path for Supervisor unit tests."""
    from palatium_ai.application.agents.harness import Harness
    from palatium_ai.application.agents.supervisor import SUPERVISOR_CONFIG, SupervisorAgent
    from palatium_ai.application.orchestration.agent_bridge import (
        supervisor_output_to_task_result,
        supervisor_to_agent_input,
    )

    harness = Harness(llm=FakeLLMPort("{}"))
    agent = SupervisorAgent(harness, SUPERVISOR_CONFIG)
    agent_input = supervisor_to_agent_input(
        task_input,  # type: ignore[arg-type]
        trace_id="trace-supervisor",
        thread_id="thread-supervisor",
    )
    output = await harness.execute_with_guardrails(agent, agent_input)
    return supervisor_output_to_task_result(
        output,
        task_id=task_input.task_id,  # type: ignore[arg-type]
        agent_role=agent.config.role,
    )


def make_supervisor_agent(harness: object | None = None) -> object:
    """SupervisorAgent bound to harness (no LLM calls)."""
    from palatium_ai.application.agents.harness import Harness
    from palatium_ai.application.agents.supervisor import SUPERVISOR_CONFIG, SupervisorAgent

    resolved = harness or Harness(llm=FakeLLMPort("{}"))
    return SupervisorAgent(resolved, SUPERVISOR_CONFIG)  # type: ignore[arg-type]


def make_critic_agent(llm: FakeLLMPort | SequentialFakeLLMPort, harness: object | None = None) -> object:
    from palatium_ai.application.agents.critic import CRITIC_CONFIG, CriticAgent
    from palatium_ai.application.agents.harness import Harness

    resolved = harness or Harness(llm=llm)  # type: ignore[arg-type]
    return CriticAgent(resolved, CRITIC_CONFIG)  # type: ignore[arg-type]


def make_formatter_agent(llm: FakeLLMPort | SequentialFakeLLMPort, harness: object | None = None) -> object:
    from palatium_ai.application.agents.formatter import FORMATTER_CONFIG, FormatterAgent
    from palatium_ai.application.agents.harness import Harness

    resolved = harness or Harness(llm=llm)  # type: ignore[arg-type]
    return FormatterAgent(resolved, FORMATTER_CONFIG)  # type: ignore[arg-type]


async def run_critic(task_input: object, llm: FakeLLMPort | SequentialFakeLLMPort):
    from palatium_ai.application.agents.critic import CRITIC_CONFIG, CriticAgent
    from palatium_ai.application.agents.harness import Harness
    from palatium_ai.application.orchestration.agent_bridge import critic_output_to_task_result, critic_to_agent_input

    harness = Harness(llm=llm)  # type: ignore[arg-type]
    agent = CriticAgent(harness, CRITIC_CONFIG)
    agent_input = critic_to_agent_input(
        task_input,  # type: ignore[arg-type]
        trace_id="trace-critic",
        thread_id="thread-critic",
    )
    output = await harness.execute_with_guardrails(agent, agent_input)
    return critic_output_to_task_result(
        output,
        task_id=task_input.task_id,  # type: ignore[arg-type]
        agent_role=agent.config.role,
    )


async def run_formatter(task_input: object, llm: FakeLLMPort | SequentialFakeLLMPort):
    from palatium_ai.application.agents.formatter import FORMATTER_CONFIG, FormatterAgent
    from palatium_ai.application.agents.harness import Harness
    from palatium_ai.application.orchestration.agent_bridge import (
        formatter_output_to_task_result,
        formatter_to_agent_input,
    )

    harness = Harness(llm=llm)  # type: ignore[arg-type]
    agent = FormatterAgent(harness, FORMATTER_CONFIG)
    agent_input = formatter_to_agent_input(
        task_input,  # type: ignore[arg-type]
        trace_id="trace-formatter",
        thread_id="thread-formatter",
    )
    output = await harness.execute_with_guardrails(agent, agent_input)
    return formatter_output_to_task_result(
        output,
        task_id=task_input.task_id,  # type: ignore[arg-type]
        agent_role=agent.config.role,
    )


async def run_memory_keeper(task_input: object, llm: FakeLLMPort | SequentialFakeLLMPort):
    from palatium_ai.application.agents.harness import Harness
    from palatium_ai.application.agents.memory_keeper import MEMORY_KEEPER_CONFIG, MemoryKeeperAgent
    from palatium_ai.application.orchestration.agent_bridge import (
        memory_keeper_output_to_task_result,
        memory_keeper_to_agent_input,
    )

    harness = Harness(llm=llm)  # type: ignore[arg-type]
    agent = MemoryKeeperAgent(harness, MEMORY_KEEPER_CONFIG)
    agent_input = memory_keeper_to_agent_input(
        task_input,  # type: ignore[arg-type]
        trace_id="trace-keeper",
        thread_id=task_input.thread_id,  # type: ignore[arg-type]
    )
    output = await harness.execute_with_guardrails(agent, agent_input)
    return memory_keeper_output_to_task_result(
        output,
        task_id=task_input.task_id,  # type: ignore[arg-type]
        agent_role=agent.config.role,
    )


def make_researcher_agent(
    llm: FakeLLMPort | SequentialFakeLLMPort,
    mcp_registry: object | None = None,
    *,
    harness: object | None = None,
) -> object:
    from palatium_ai.application.agents.harness import Harness
    from palatium_ai.application.agents.researcher import RESEARCHER_CONFIG, ResearcherAgent

    resolved = harness or Harness(llm=llm)  # type: ignore[arg-type]
    return ResearcherAgent(
        resolved,  # type: ignore[arg-type]
        RESEARCHER_CONFIG,
        llm,  # type: ignore[arg-type]
        mcp_registry=mcp_registry,  # type: ignore[arg-type]
    )


def make_coder_agent(*, harness: object | None = None) -> object:
    from palatium_ai.application.agents.coder import CODER_CONFIG, CoderAgent
    from palatium_ai.application.agents.harness import Harness

    resolved = harness or Harness(llm=FakeLLMPort("{}"))
    return CoderAgent(resolved, CODER_CONFIG)  # type: ignore[arg-type]


def make_analyst_agent(*, harness: object | None = None) -> object:
    from palatium_ai.application.agents.analyst import ANALYST_CONFIG, AnalystAgent
    from palatium_ai.application.agents.harness import Harness

    resolved = harness or Harness(llm=FakeLLMPort("{}"))
    return AnalystAgent(resolved, ANALYST_CONFIG)  # type: ignore[arg-type]


def make_continuation_agent(*, harness: object | None = None) -> object:
    from palatium_ai.application.agents.context_enricher import CONTEXTUALIZER_CONFIG, ContextualizerAgent
    from palatium_ai.application.agents.harness import Harness

    resolved = harness or Harness(llm=FakeLLMPort("{}"))
    return ContextualizerAgent(resolved, CONTEXTUALIZER_CONFIG)  # type: ignore[arg-type]


def make_weaving_agent(
    mcp_registry: object | None = None,
    *,
    harness: object | None = None,
) -> object:
    from palatium_ai.application.agents.context_enricher import CONTEXT_WEAVER_CONFIG, ContextWeaverAgent
    from palatium_ai.application.agents.harness import Harness

    resolved = harness or Harness(llm=FakeLLMPort("{}"))
    return ContextWeaverAgent(resolved, CONTEXT_WEAVER_CONFIG, mcp_registry=mcp_registry)  # type: ignore[arg-type]


async def run_context_weaver(task_input: object, mcp_registry: object | None = None):
    from palatium_ai.application.agents.context_enricher import CONTEXT_WEAVER_CONFIG, ContextWeaverAgent
    from palatium_ai.application.agents.harness import Harness
    from palatium_ai.application.orchestration.agent_bridge import (
        context_weaver_output_to_task_result,
        context_weaver_to_agent_input,
    )

    harness = Harness(llm=FakeLLMPort("{}"))
    agent = ContextWeaverAgent(harness, CONTEXT_WEAVER_CONFIG, mcp_registry=mcp_registry)  # type: ignore[arg-type]
    agent_input = context_weaver_to_agent_input(
        task_input,  # type: ignore[arg-type]
        trace_id="trace-weaver",
        thread_id="thread-weaver",
    )
    output = await harness.execute_with_guardrails(agent, agent_input)
    return context_weaver_output_to_task_result(
        output,
        task_id=task_input.task_id,  # type: ignore[arg-type]
        agent_role=agent.config.role,
    )


def make_dual_agent_stack(
    contextualizer_response: str,
    intent_response: str,
) -> tuple[object, object, object, SequentialFakeLLMPort]:
    """Shared harness for contextualizer → intent graph order in integration tests."""
    from palatium_ai.application.agents.context_enricher import CONTEXTUALIZER_CONFIG, ContextualizerAgent
    from palatium_ai.application.agents.harness import Harness
    from palatium_ai.application.agents.intent_classifier import INTENT_CLASSIFIER_CONFIG, IntentClassifierAgent

    llm = SequentialFakeLLMPort([contextualizer_response, intent_response])
    harness = Harness(llm=llm)
    return (
        harness,
        ContextualizerAgent(harness, CONTEXTUALIZER_CONFIG),
        IntentClassifierAgent(harness, INTENT_CLASSIFIER_CONFIG),
        llm,
    )


def pytest_collection_modifyitems(items: list[pytest.Item]) -> None:
    """Skip llm_live tests unless PALATIUM_EVAL_LIVE_JUDGE=1 (075)."""
    import os

    if os.environ.get("PALATIUM_EVAL_LIVE_JUDGE") == "1":
        return
    skip_live = pytest.mark.skip(reason="llm_live requires PALATIUM_EVAL_LIVE_JUDGE=1")
    for item in items:
        if "llm_live" in item.keywords:
            item.add_marker(skip_live)

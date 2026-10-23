"""Researcher re-reads a thread file with deterministically resolved arguments (070, 020).

The model never chooses the file: ``attachment_id`` comes from the resolver, and a
failure to resolve is a typed refusal instead of a tool call with an invented id.
"""

from __future__ import annotations

import json

from uuid import uuid4

import pytest

from palatium_ai.application.agents.evals.cassette import (
    _packet_from_raw,
    _ResearcherEvalMcpRegistry,
)
from palatium_ai.application.agents.evals.static_llm import SequentialStaticLLMPort
from palatium_ai.application.agents.harness import Harness
from palatium_ai.application.agents.researcher import RESEARCHER_CONFIG, ResearcherAgent
from palatium_ai.application.orchestration.agent_bridge import researcher_to_agent_input
from palatium_ai.domain.agents.messages import AgentOutput
from palatium_ai.domain.agents.researcher import ATTACHMENT_REFERENCE_UNRESOLVED, ResearcherInput, ResearcherOutput
from palatium_ai.domain.mcp.models import MCPToolCall, MCPToolDescriptor, MCPToolResult
from palatium_ai.domain.mcp.platform_schemas import PLATFORM_READ_ATTACHMENT_SCHEMA
from palatium_ai.domain.memory.tool_output import wrap_untrusted_tool_output
from palatium_ai.domain.policies.file_reference import (
    FileRefCandidate,
    FileReferencePolicy,
    FileReferenceResolution,
)

_SYNTHESIS = json.dumps(
    {
        "summary": "Файл перечитан: структура и требования приведены ниже.",
        "confidence": 0.88,
        "sources_used": ["mcp:platform.read_attachment"],
    },
    ensure_ascii=False,
)
_FILE_TEXT = "Раздел 1. Требования к системе. Срок внедрения — 2025 год."
_ATTACHMENT_ID = uuid4()


class _ReadRegistry(_ResearcherEvalMcpRegistry):
    """Eval registry with the pinned Host-local ``read_attachment`` tool exposed."""

    def __init__(self) -> None:
        super().__init__()
        self._tools["platform"].append(
            MCPToolDescriptor(
                name="read_attachment",
                description="Read the extracted text of an owner-scoped attachment.",
                input_schema=PLATFORM_READ_ATTACHMENT_SCHEMA,
                annotations={"readOnlyHint": True},
            ),
        )

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
            content=[
                {
                    "type": "text",
                    "text": wrap_untrusted_tool_output(_FILE_TEXT, source=f"attachment:{_ATTACHMENT_ID}"),
                },
            ],
            is_error=False,
        )


class _FakeResolver:
    def __init__(self, resolution: FileReferenceResolution) -> None:
        self._resolution = resolution
        self.calls: list[dict[str, str]] = []

    async def resolve(self, **kwargs: str) -> FileReferenceResolution:
        self.calls.append({key: str(value) for key, value in kwargs.items()})
        return self._resolution


def _resolved() -> FileReferenceResolution:
    return FileReferencePolicy.resolve(
        [FileRefCandidate(attachment_id=_ATTACHMENT_ID, filename="СФУТ 9.03-2025.pdf")],
        hint_text="а из БД взять этот файл и ещё раз прочитать",
    )


def _refused() -> FileReferenceResolution:
    return FileReferencePolicy.resolve([], hint_text="а из БД взять этот файл и ещё раз прочитать")


def _packet(task_id: str):
    return _packet_from_raw(
        {
            "user_text": "а из БД взять этот файл и ещё раз прочитать",
            "task_kind": "knowledge_request",
            "route": "researcher",
            "requires_mcp": True,
            "requires_tool_call": True,
            "selected_strategy": "direct_tool_call",
            "server_name": "platform",
            "tool_name": "read_attachment",
            "route_plan": "thread file re-read from storage",
        },
        task_id,
    )


async def _run(
    resolver: _FakeResolver | None,
) -> tuple[AgentOutput, SequentialStaticLLMPort, _ReadRegistry]:
    task_id = str(uuid4())
    llm = SequentialStaticLLMPort([_SYNTHESIS])
    registry = _ReadRegistry()
    harness = Harness(llm=llm)
    agent = ResearcherAgent(
        harness,
        RESEARCHER_CONFIG,
        llm,
        mcp_registry=registry,
        file_reference_resolver=resolver,  # type: ignore[arg-type]  # duck-typed fake (017)
    )
    output = await harness.execute_with_guardrails(
        agent,
        researcher_to_agent_input(
            ResearcherInput(task_id=task_id, context_packet=_packet(task_id)),
            trace_id="file-reread",
            thread_id="thread-reread",
            user_id="actor-user",
        ),
    )
    return output, llm, registry


@pytest.mark.asyncio()
async def test_resolved_reference_reads_the_file_without_an_arguments_llm_call() -> None:
    output, llm, registry = await _run(_FakeResolver(_resolved()))

    assert output.status == "success"
    assert isinstance(output.output, ResearcherOutput)
    assert registry.calls, "read_attachment must be invoked"
    server_name, call = registry.calls[0]
    assert (server_name, call.name) == ("platform", "read_attachment")
    assert call.arguments["attachment_id"] == str(_ATTACHMENT_ID)
    # Actor identity is bound from the agent context, never authored by the model (020).
    assert call.arguments["user_id"] == "actor-user"
    # Deterministic arguments → the only LLM call is the synthesis step.
    assert len(llm.calls) == 1
    assert "UNTRUSTED_TOOL_OUTPUT" not in output.output.summary


@pytest.mark.asyncio()
async def test_unresolved_reference_refuses_instead_of_guessing() -> None:
    output, llm, registry = await _run(_FakeResolver(_refused()))

    assert registry.calls == []
    assert output.status == "failure"
    assert output.error_message == ATTACHMENT_REFERENCE_UNRESOLVED
    assert isinstance(output.output, ResearcherOutput)
    assert "загруженных файлов" in output.output.summary
    assert llm.calls == []


@pytest.mark.asyncio()
async def test_missing_resolver_fails_closed_without_a_tool_call() -> None:
    output, _, registry = await _run(None)

    assert registry.calls == []
    assert output.status == "failure"
    assert output.error_message == ATTACHMENT_REFERENCE_UNRESOLVED
    assert isinstance(output.output, ResearcherOutput)
    from palatium_ai.domain.policies.internal_vocabulary import InternalVocabularyPolicy

    assert InternalVocabularyPolicy.find_terms(output.output.summary) == ()


@pytest.mark.asyncio()
async def test_file_hint_never_contains_assistant_prose_or_memory_hints() -> None:
    """Regression: the previous answer's «обращение» must not leak into file resolution.

    Assistant text and extracted facts are not evidence of which file the user
    meant — they made a bare word resolve an unrelated thread file (055).
    """
    task_id = str(uuid4())
    llm = SequentialStaticLLMPort([_SYNTHESIS])
    registry = _ReadRegistry()
    harness = Harness(llm=llm)
    resolver = _FakeResolver(_refused())
    agent = ResearcherAgent(
        harness,
        RESEARCHER_CONFIG,
        llm,
        mcp_registry=registry,
        file_reference_resolver=resolver,  # type: ignore[arg-type]  # duck-typed fake (017)
    )

    await harness.execute_with_guardrails(
        agent,
        researcher_to_agent_input(
            ResearcherInput(
                task_id=task_id,
                context_packet=_packet(task_id),
                prior_context="В ответ на Ваше обращение сообщаем следующее: документ принят.",
                memory_hints=("Пользователь прикладывал Обращение.docx",),
            ),
            trace_id="file-reread",
            thread_id="thread-reread",
            user_id="actor-user",
        ),
    )

    assert resolver.calls, "resolver must be consulted before the tool call"
    hint = resolver.calls[0]["hint_text"]
    assert hint == "а из БД взять этот файл и ещё раз прочитать"
    assert "обращение" not in hint.casefold()


@pytest.mark.asyncio()
async def test_refusal_text_never_names_internal_context_fields() -> None:
    output, _, _ = await _run(_FakeResolver(_refused()))

    assert isinstance(output.output, ResearcherOutput)
    summary = output.output.summary
    for leaked in ("attachment_context", "prior_context", "memory_hints", "context_packet"):
        assert leaked not in summary

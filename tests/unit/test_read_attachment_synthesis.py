"""Singular read_attachment seals only for verbatim; analysis asks synthesize (055)."""

from __future__ import annotations

import json

from types import SimpleNamespace
from uuid import UUID, uuid4

import pytest

from palatium_ai.application.agents.researcher.config import RESEARCHER_CONFIG
from palatium_ai.application.agents.researcher.mcp_path import McpPathDeps, mcp_outcome_to_output
from palatium_ai.application.tools.mcp import MCPToolCallOutcome
from palatium_ai.domain.agents.context_packet import ContextPacket
from palatium_ai.domain.agents.researcher import ResearcherInput, ResearcherOutput
from palatium_ai.domain.mcp.models import ToolExecutionPlan
from palatium_ai.domain.policies.types import VERBATIM_EXTRACTION_CAPABILITY

_ATTACHMENT_ID = "aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa"
_CONTRACT_BODY = "ДОГОВОР № 15/2026\n" + ("пункт. " * 400)


def _envelope(body: str) -> str:
    return json.dumps(
        {
            "tool": "read_attachment",
            "attachment_id": _ATTACHMENT_ID,
            "filename": "Договор.docx",
            "fenced_text": body,
            "total_chars": len(body),
        },
        ensure_ascii=False,
    )


def _packet(
    *,
    strategy: str,
    capabilities: tuple[str, ...] = (),
    response_shape: str = "auto",
) -> ContextPacket:
    return ContextPacket(
        task_id="t-rec",
        user_text="дай по нему рекомендации",
        task_kind="knowledge_request",
        route="researcher",
        route_plan="read then reason",
        requires_mcp=True,
        candidate_capabilities=capabilities,
        response_shape=response_shape,  # type: ignore[arg-type]
        execution_plan=ToolExecutionPlan(
            strategy=strategy,  # type: ignore[arg-type]
            capability="attachments",
            server_name="platform",
            tool_name="read_attachment",
            requires_tool_call=True,
            rationale="test",
        ),
        context_summary="thread file",
        untrusted_context="",
    )


class _Harness:
    def __init__(self) -> None:
        self.calls = 0

    async def call_llm(self, *_args: object, **_kwargs: object) -> SimpleNamespace:
        self.calls += 1
        return SimpleNamespace(
            content=json.dumps(
                {
                    "summary": "Рекомендации: уточнить срок и ответственность сторон.",
                    "confidence": 0.9,
                    "sources_used": ["mcp:platform.read_attachment"],
                },
                ensure_ascii=False,
            )
        )


def _deps(harness: _Harness) -> McpPathDeps:
    return McpPathDeps(
        config=RESEARCHER_CONFIG,
        harness=harness,  # type: ignore[arg-type]
        mcp_registry=object(),  # type: ignore[arg-type]
        capability_index=object(),  # type: ignore[arg-type]
        tool_executor=object(),  # type: ignore[arg-type]
        argument_builder=object(),  # type: ignore[arg-type]
        mcp_tool_call_repository=None,
        agent_role="researcher",
    )


@pytest.mark.asyncio()
async def test_analysis_read_attachment_synthesizes_instead_of_dumping_body() -> None:
    harness = _Harness()
    outcome = MCPToolCallOutcome(content=[{"type": "text", "text": _envelope(_CONTRACT_BODY)}])
    output = await mcp_outcome_to_output(
        _deps(harness),
        ResearcherInput(task_id="t-rec", context_packet=_packet(strategy="retrieve_then_reason")),
        outcome,
        "platform",
        "read_attachment",
        UUID(_ATTACHMENT_ID),
    )

    assert harness.calls == 1
    assert isinstance(output.output, ResearcherOutput)
    assert "Рекомендации" in output.output.summary
    assert "ДОГОВОР № 15/2026" not in output.output.summary
    assert len(output.output.summary) < 500


@pytest.mark.asyncio()
async def test_analysis_output_carries_evidence_for_pii_checks() -> None:
    """Critic may quote a requisite of the user's own file without a false leak (020)."""
    harness = _Harness()
    outcome = MCPToolCallOutcome(content=[{"type": "text", "text": _envelope(_CONTRACT_BODY)}])
    output = await mcp_outcome_to_output(
        _deps(harness),
        ResearcherInput(task_id="t-rec", context_packet=_packet(strategy="retrieve_then_reason")),
        outcome,
        "platform",
        "read_attachment",
        uuid4(),
    )

    assert isinstance(output.output, ResearcherOutput)
    assert "ДОГОВОР № 15/2026" in output.output.evidence_excerpt
    assert output.output.evidence_excerpt.strip()


@pytest.mark.asyncio()
async def test_long_document_is_read_in_bounded_chunks() -> None:
    """A 30k+ body is mapped part by part, then reduced — never truncated to its head."""
    from palatium_ai.domain.policies.document_synthesis import DocumentSynthesisPolicy

    body = "ДОГОВОР № 15/2026\n" + ("Пункт о сроках оплаты и ответственности сторон. " * 800)
    assert len(body) > 12_000
    expected = DocumentSynthesisPolicy.plan(body, budget_chars=12_000, max_chunks=8)
    assert len(expected) > 1

    harness = _Harness()
    outcome = MCPToolCallOutcome(content=[{"type": "text", "text": _envelope(body)}])
    output = await mcp_outcome_to_output(
        _deps(harness),
        ResearcherInput(task_id="t-rec", context_packet=_packet(strategy="retrieve_then_reason")),
        outcome,
        "platform",
        "read_attachment",
        uuid4(),
    )

    assert harness.calls == len(expected) + 1  # map per part + one reduce
    assert isinstance(output.output, ResearcherOutput)
    assert "Рекомендации" in output.output.summary


@pytest.mark.asyncio()
async def test_verbatim_read_attachment_seals_body_without_synthesis() -> None:
    harness = _Harness()
    body = "Точный OCR-текст файла."
    outcome = MCPToolCallOutcome(content=[{"type": "text", "text": _envelope(body)}])
    output = await mcp_outcome_to_output(
        _deps(harness),
        ResearcherInput(
            task_id="t-rec",
            context_packet=_packet(
                strategy="direct_tool_call",
                capabilities=(VERBATIM_EXTRACTION_CAPABILITY,),
            ),
        ),
        outcome,
        "platform",
        "read_attachment",
        uuid4(),
    )

    assert harness.calls == 0
    assert isinstance(output.output, ResearcherOutput)
    assert output.output.summary == body


@pytest.mark.asyncio()
async def test_analysis_shape_blocks_mcp_seal_even_with_verbatim_tag() -> None:
    """Defense-in-depth on the MCP path: mistagged capability under analysis synthesizes."""
    harness = _Harness()
    outcome = MCPToolCallOutcome(content=[{"type": "text", "text": _envelope(_CONTRACT_BODY)}])
    output = await mcp_outcome_to_output(
        _deps(harness),
        ResearcherInput(
            task_id="t-rec",
            context_packet=_packet(
                strategy="direct_tool_call",
                capabilities=(VERBATIM_EXTRACTION_CAPABILITY,),
                response_shape="document_analysis",
            ),
        ),
        outcome,
        "platform",
        "read_attachment",
        uuid4(),
    )

    assert harness.calls == 1
    assert isinstance(output.output, ResearcherOutput)
    assert "Рекомендации" in output.output.summary
    assert "ДОГОВОР № 15/2026" not in output.output.summary

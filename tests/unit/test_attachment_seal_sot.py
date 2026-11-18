"""Seal SoT shared by fence reason_only, MCP read_attachment, Formatter and Critic (055)."""

from __future__ import annotations

from uuid import uuid4

import pytest

from palatium_ai.application.agents.researcher.llm_research import _try_seal_attachment_fence
from palatium_ai.domain.agents.context_packet import ContextPacket
from palatium_ai.domain.agents.researcher import ResearcherInput, ResearcherOutput
from palatium_ai.domain.mcp.models import ToolExecutionPlan
from palatium_ai.domain.memory.tool_output import wrap_untrusted_tool_output
from palatium_ai.domain.policies.file_reference import FileReferencePolicy
from palatium_ai.domain.policies.types import VERBATIM_EXTRACTION_CAPABILITY

_FENCE_BODY = "[[page 1]]\nДОГОВОР № 15/2026\nОбязательства сторон.\n[[page 2]]\nПодписи."


def _input(*, capabilities: tuple[str, ...], response_shape: str = "auto") -> ResearcherInput:
    fence = wrap_untrusted_tool_output(_FENCE_BODY, source="attachment:doc")
    return ResearcherInput(
        task_id="t-seal",
        context_packet=ContextPacket(
            task_id="t-seal",
            user_text="дай полный текст файла",
            task_kind="knowledge_request",
            route="researcher",
            route_plan="reason over the fence",
            requires_mcp=False,
            candidate_capabilities=capabilities,
            response_shape=response_shape,  # type: ignore[arg-type]
            execution_plan=ToolExecutionPlan(
                strategy="reason_only",
                requires_tool_call=False,
                rationale="attachment fence already present",
            ),
            context_summary="upload",
            untrusted_context=fence,
        ),
    )


@pytest.mark.asyncio()
async def test_fence_extract_seals_body_without_llm_and_drops_page_markers() -> None:
    output = _try_seal_attachment_fence(
        _input(capabilities=(VERBATIM_EXTRACTION_CAPABILITY,)),
        task_id=uuid4(),
        confidence_threshold=0.7,
    )

    assert output is not None
    assert isinstance(output.output, ResearcherOutput)
    assert output.output.summary.startswith("ДОГОВОР № 15/2026")
    assert "[[page" not in output.output.summary
    assert "UNTRUSTED_TOOL_OUTPUT" not in output.output.summary
    # The sealed body is this turn's evidence: quoting its requisites is legitimate.
    assert "ДОГОВОР № 15/2026" in output.output.evidence_excerpt


@pytest.mark.asyncio()
async def test_summary_ask_is_not_sealed_from_fence() -> None:
    assert (
        _try_seal_attachment_fence(
            _input(capabilities=("summarize",)),
            task_id=uuid4(),
            confidence_threshold=0.7,
        )
        is None
    )


@pytest.mark.asyncio()
async def test_analysis_shape_blocks_fence_seal_even_with_verbatim_tag() -> None:
    assert (
        _try_seal_attachment_fence(
            _input(
                capabilities=(VERBATIM_EXTRACTION_CAPABILITY,),
                response_shape="document_analysis",
            ),
            task_id=uuid4(),
            confidence_threshold=0.7,
        )
        is None
    )


@pytest.mark.asyncio()
async def test_no_fence_means_no_seal() -> None:
    task_input = _input(capabilities=(VERBATIM_EXTRACTION_CAPABILITY,))
    packet = task_input.context_packet.model_copy(update={"untrusted_context": ""})

    assert (
        _try_seal_attachment_fence(
            task_input.model_copy(update={"context_packet": packet}),
            task_id=uuid4(),
            confidence_threshold=0.7,
        )
        is None
    )


def test_same_policy_gates_formatter_critic_and_researcher() -> None:
    """One SoT call shape — four call sites must agree on the seal verdict."""
    caps = (VERBATIM_EXTRACTION_CAPABILITY,)

    assert FileReferencePolicy.seals_thread_file_body(candidate_capabilities=caps) is True
    assert (
        FileReferencePolicy.seals_thread_file_body(
            candidate_capabilities=caps,
            response_shape="document_analysis",
        )
        is False
    )

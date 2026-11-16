"""P0.3: attachment unresolved keeps RU policy copy through Formatter (no EN rewrite)."""

from __future__ import annotations

from uuid import uuid4

from palatium_ai.application.agents.formatter.fast_path import try_formatter_fast_path
from palatium_ai.application.agents.researcher.outcomes import failure_output
from palatium_ai.application.orchestration.agent_bridge import researcher_output_to_task_result
from palatium_ai.application.orchestration.node_inputs import build_formatter_input
from palatium_ai.application.orchestration.snapshot import OrchestrationSnapshot
from palatium_ai.domain.agents.context_packet import ContextPacket
from palatium_ai.domain.agents.formatter import FormatterInput
from palatium_ai.domain.agents.intent import IntentClassifierOutput, IntentTaskResult
from palatium_ai.domain.agents.researcher import (
    ATTACHMENT_REFERENCE_UNRESOLVED,
    ResearcherOutput,
    ResearcherTaskResult,
)
from palatium_ai.domain.agents.supervisor import SupervisorOutput, SupervisorTaskResult
from palatium_ai.domain.mcp.models import ToolExecutionPlan
from palatium_ai.domain.policies.file_reference import FileReferencePolicy, FileReferenceResolution

_RU_REFUSAL = FileReferencePolicy.refusal_message(
    FileReferenceResolution(
        status="no_match",
        reason="name_not_in_thread",
        requested_name="QX-77",
        candidates=(),
    )
)


def _classification() -> IntentTaskResult:
    return IntentTaskResult(
        task_id="t1",
        agent_role="intent_classifier",
        status="success",
        confidence=0.9,
        requires_review=False,
        output=IntentClassifierOutput(
            task_kind="knowledge_request",
            requires_mcp=True,
            candidate_capabilities=("read_attachment",),
            confidence=0.9,
            reasoning="Thread file re-read.",
            file_reference="thread_file",
        ),
    )


def _routing() -> SupervisorTaskResult:
    return SupervisorTaskResult(
        task_id="t1",
        agent_role="supervisor",
        status="success",
        confidence=0.9,
        requires_review=False,
        output=SupervisorOutput(
            route="researcher",
            confidence=0.9,
            target_agent="researcher",
            plan="Resolve thread file reference.",
        ),
    )


def test_bridge_keeps_refusal_summary_without_review() -> None:
    output = failure_output(uuid4(), summary=_RU_REFUSAL, error=ATTACHMENT_REFERENCE_UNRESOLVED)
    result = researcher_output_to_task_result(output, task_id="t1", agent_role="researcher")
    assert result.status == "partial"
    assert result.requires_review is False
    assert result.error == ATTACHMENT_REFERENCE_UNRESOLVED
    assert result.output is not None
    assert result.output.summary == _RU_REFUSAL
    assert result.cannot_answer_without_source is False


def test_formatter_input_marks_attachment_unresolved_as_policy_refusal() -> None:
    state = {
        "task_id": "t1",
        "thread_id": "th1",
        "user_text": "перечитай QX-77",
        "response_locale": "ru-RU",
        "classification": _classification(),
        "routing": _routing(),
        "execution": ResearcherTaskResult(
            task_id="t1",
            agent_role="researcher",
            status="partial",
            confidence=0.0,
            requires_review=False,
            output=ResearcherOutput(summary=_RU_REFUSAL, confidence=0.0, sources_used=()),
            error=ATTACHMENT_REFERENCE_UNRESOLVED,
        ),
    }
    snapshot = OrchestrationSnapshot.from_state(state)  # type: ignore[arg-type]
    fmt = build_formatter_input(snapshot, state)  # type: ignore[arg-type]
    assert fmt.policy_refusal is True
    assert fmt.worker_summary == _RU_REFUSAL


def test_fast_path_emits_ru_refusal_verbatim() -> None:
    packet = ContextPacket(
        task_id="t1",
        user_text="перечитай QX-77",
        task_kind="knowledge_request",
        route="researcher",
        route_plan="read file",
        requires_mcp=True,
        candidate_capabilities=("read_attachment",),
        execution_plan=ToolExecutionPlan(
            strategy="direct_tool_call",
            requires_tool_call=True,
            rationale="thread file",
        ),
        context_summary="s",
    )
    result = try_formatter_fast_path(
        task_input=FormatterInput(
            task_id="t1",
            context_packet=packet,
            worker_summary=_RU_REFUSAL,
            response_locale="ru-RU",
            policy_refusal=True,
        ),
        task_kind="knowledge_request",
        selected_strategy="direct_tool_call",
        worker_confidence=0.0,
    )
    assert result is not None
    assert result.output is not None
    assert result.output.plain_text().strip() == _RU_REFUSAL
    assert "upload" not in result.output.plain_text().lower()
    assert "please" not in result.output.plain_text().lower()

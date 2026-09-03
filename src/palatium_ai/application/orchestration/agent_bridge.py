# src/palatium_ai/application/orchestration/agent_bridge.py

"""Bridge legacy TaskResult graph state ↔ BaseAgent AgentInput/AgentOutput (migration)."""

from __future__ import annotations

import json

from typing import TYPE_CHECKING
from uuid import NAMESPACE_DNS, UUID, uuid5

from palatium_ai.domain.agents.analyst import AnalystInput, AnalystOutput
from palatium_ai.domain.agents.coder import CoderInput, CoderOutput
from palatium_ai.domain.agents.context_weaver import (
    ContextWeaverInput,
    ContextWeaverOutput,
    ContextWeaverTaskResult,
)
from palatium_ai.domain.agents.critic import CriticInput, CriticOutput, CriticTaskResult
from palatium_ai.domain.agents.formatter import FormatterInput, FormatterTaskResult
from palatium_ai.domain.agents.intent import IntentClassifierInput, IntentClassifierOutput, IntentTaskResult
from palatium_ai.domain.agents.memory_keeper import (
    MemoryKeeperInput,
    MemoryKeeperOutput,
    MemoryKeeperTaskResult,
)
from palatium_ai.domain.agents.messages import AgentInput, AgentOutput
from palatium_ai.domain.agents.researcher import ResearcherInput, ResearcherOutput, ResearcherTaskResult
from palatium_ai.domain.agents.supervisor import SupervisorInput, SupervisorOutput, SupervisorTaskResult
from palatium_ai.domain.agents.text_ingestor import TextIngestorInput, TextIngestorOutput, TextIngestorTaskResult
from palatium_ai.domain.content import ContentDocument
from palatium_ai.domain.memory.contextualizer import ContextualizerInput, ContextualizerOutput, ContextualizerTaskResult

if TYPE_CHECKING:
    from palatium_ai.domain.policies.types import ContinuationKind


def task_id_to_uuid(task_id: str) -> UUID:
    """Map graph string task_id to AgentInput UUID (stable for non-UUID ids)."""
    try:
        return UUID(task_id)
    except ValueError:
        return uuid5(NAMESPACE_DNS, task_id)


def intent_to_agent_input(
    task_input: IntentClassifierInput,
    *,
    trace_id: str,
    thread_id: str,
) -> AgentInput:
    """Build AgentInput for IntentClassifier from graph node payload."""
    continuation: ContinuationKind | None = task_input.continuation_kind
    return AgentInput(
        task_id=task_id_to_uuid(task_input.task_id),
        trace_id=trace_id,
        instruction=task_input.text,
        context={
            "continuation_kind": continuation or "",
            "has_prior_dialog": "true" if task_input.has_prior_dialog else "false",
            "_thread_id": thread_id,
        },
    )


def intent_output_to_task_result(agent_output: AgentOutput, *, task_id: str, agent_role: str) -> IntentTaskResult:
    """Map harness AgentOutput back to graph IntentTaskResult."""
    parsed: IntentClassifierOutput | None = None
    if isinstance(agent_output.output, IntentClassifierOutput):
        parsed = agent_output.output

    if agent_output.status == "failure":
        return IntentTaskResult(
            task_id=task_id,
            agent_role=agent_role,
            status="failure",
            confidence=agent_output.confidence,
            requires_review=True,
            output=None,
            error=agent_output.error_message or "intent_classifier failed",
        )

    requires_review = agent_output.status == "partial"
    return IntentTaskResult(
        task_id=task_id,
        agent_role=agent_role,
        status=agent_output.status,
        confidence=agent_output.confidence,
        requires_review=requires_review,
        output=parsed,
        error=agent_output.error_message,
    )


def contextualizer_to_agent_input(
    task_input: ContextualizerInput,
    *,
    trace_id: str,
    thread_id: str,
) -> AgentInput:
    """Build AgentInput for Contextualizer from graph node payload."""
    task_kind = task_input.task_kind or ""
    return AgentInput(
        task_id=task_id_to_uuid(task_input.task_id),
        trace_id=trace_id,
        instruction=task_input.user_text,
        context={
            "dialog_window_json": task_input.dialog_window.model_dump_json(),
            "memory_hints_json": json.dumps(list(task_input.memory_hints), ensure_ascii=False),
            "prompt_budget_json": task_input.prompt_budget.model_dump_json(),
            "task_kind": task_kind,
            "requires_mcp": "true" if task_input.requires_mcp else "false",
            "_thread_id": thread_id,
        },
    )


def contextualizer_output_to_task_result(
    agent_output: AgentOutput,
    *,
    task_id: str,
    agent_role: str,
) -> ContextualizerTaskResult:
    """Map harness AgentOutput back to graph ContextualizerTaskResult."""
    parsed: ContextualizerOutput | None = None
    if isinstance(agent_output.output, ContextualizerOutput):
        parsed = agent_output.output

    if agent_output.status == "failure":
        return ContextualizerTaskResult(
            task_id=task_id,
            agent_role=agent_role,
            status="failure",
            confidence=agent_output.confidence,
            requires_review=True,
            output=None,
            error=agent_output.error_message or "contextualizer failed",
        )

    requires_review = agent_output.status == "partial"
    return ContextualizerTaskResult(
        task_id=task_id,
        agent_role=agent_role,
        status=agent_output.status,
        confidence=agent_output.confidence,
        requires_review=requires_review,
        output=parsed,
        error=agent_output.error_message,
    )


def supervisor_to_agent_input(
    task_input: SupervisorInput,
    *,
    trace_id: str,
    thread_id: str,
) -> AgentInput:
    """Build AgentInput for Supervisor from graph node payload."""
    return AgentInput(
        task_id=task_id_to_uuid(task_input.task_id),
        trace_id=trace_id,
        instruction=task_input.user_text,
        context={
            "task_kind": task_input.task_kind,
            "requires_mcp": "true" if task_input.requires_mcp else "false",
            "classification_confidence": str(task_input.classification_confidence),
            "candidate_capabilities_json": json.dumps(list(task_input.candidate_capabilities), ensure_ascii=False),
            "_thread_id": thread_id,
        },
    )


def supervisor_output_to_task_result(
    agent_output: AgentOutput,
    *,
    task_id: str,
    agent_role: str,
) -> SupervisorTaskResult:
    """Map harness AgentOutput back to graph SupervisorTaskResult."""
    parsed: SupervisorOutput | None = None
    if isinstance(agent_output.output, SupervisorOutput):
        parsed = agent_output.output

    if agent_output.status == "failure":
        return SupervisorTaskResult(
            task_id=task_id,
            agent_role=agent_role,
            status="failure",
            confidence=agent_output.confidence,
            requires_review=True,
            output=None,
            error=agent_output.error_message or "supervisor failed",
        )

    requires_review = agent_output.status == "partial"
    return SupervisorTaskResult(
        task_id=task_id,
        agent_role=agent_role,
        status=agent_output.status,
        confidence=agent_output.confidence,
        requires_review=requires_review,
        output=parsed,
        error=agent_output.error_message,
    )


def critic_to_agent_input(
    task_input: CriticInput,
    *,
    trace_id: str,
    thread_id: str,
) -> AgentInput:
    """Build AgentInput for Critic from graph node payload."""
    return AgentInput(
        task_id=task_id_to_uuid(task_input.task_id),
        trace_id=trace_id,
        instruction=task_input.context_packet.user_text,
        context={
            "context_packet_json": task_input.context_packet.model_dump_json(),
            "classification_confidence": str(task_input.classification_confidence),
            "classification_reasoning": task_input.classification_reasoning,
            "worker_summary": task_input.worker_summary or "",
            "selected_strategy": task_input.selected_strategy,
            "continuation_kind": task_input.continuation_kind or "",
            "user_input_chars": str(task_input.user_input_chars),
            "_task_id": task_input.task_id,
            "_thread_id": thread_id,
        },
    )


def critic_output_to_task_result(
    agent_output: AgentOutput,
    *,
    task_id: str,
    agent_role: str,
) -> CriticTaskResult:
    """Map harness AgentOutput back to graph CriticTaskResult."""
    parsed: CriticOutput | None = None
    if isinstance(agent_output.output, CriticOutput):
        parsed = agent_output.output

    if agent_output.status == "failure":
        return CriticTaskResult(
            task_id=task_id,
            agent_role=agent_role,
            status="failure",
            confidence=agent_output.confidence,
            requires_review=True,
            output=None,
            error=agent_output.error_message or "critic failed",
        )

    requires_review = agent_output.status == "partial"
    if parsed is not None:
        requires_review = requires_review or parsed.requires_review
    return CriticTaskResult(
        task_id=task_id,
        agent_role=agent_role,
        status=agent_output.status,
        confidence=agent_output.confidence,
        requires_review=requires_review,
        output=parsed,
        error=agent_output.error_message,
    )


def formatter_to_agent_input(
    task_input: FormatterInput,
    *,
    trace_id: str,
    thread_id: str,
) -> AgentInput:
    """Build AgentInput for Formatter from graph node payload."""
    return AgentInput(
        task_id=task_id_to_uuid(task_input.task_id),
        trace_id=trace_id,
        instruction=task_input.context_packet.user_text,
        context={
            "context_packet_json": task_input.context_packet.model_dump_json(),
            "worker_summary": task_input.worker_summary or "",
            "critic_summary": task_input.critic_summary or "",
            "requires_review": "true" if task_input.requires_review else "false",
            "requires_user_choice": "true" if task_input.requires_user_choice else "false",
            "underspecification_kind": task_input.underspecification_kind,
            "revision_feedback": task_input.revision_feedback or "",
            "_task_id": task_input.task_id,
            "_thread_id": thread_id,
        },
    )


def formatter_output_to_task_result(
    agent_output: AgentOutput,
    *,
    task_id: str,
    agent_role: str,
) -> FormatterTaskResult:
    """Map harness AgentOutput back to graph FormatterTaskResult."""
    parsed: ContentDocument | None = None
    if isinstance(agent_output.output, ContentDocument):
        parsed = agent_output.output

    if agent_output.status == "failure":
        return FormatterTaskResult(
            task_id=task_id,
            agent_role=agent_role,
            status="failure",
            confidence=agent_output.confidence,
            requires_review=True,
            output=None,
            error=agent_output.error_message or "formatter failed",
        )

    requires_review = agent_output.status == "partial"
    if parsed is not None:
        requires_review = requires_review or parsed.meta.requires_review
    return FormatterTaskResult(
        task_id=task_id,
        agent_role=agent_role,
        status=agent_output.status,
        confidence=agent_output.confidence,
        requires_review=requires_review,
        output=parsed,
        error=agent_output.error_message,
    )


def context_weaver_to_agent_input(
    task_input: ContextWeaverInput,
    *,
    trace_id: str,
    thread_id: str,
) -> AgentInput:
    """Build AgentInput for ContextWeaver from graph node payload."""
    return AgentInput(
        task_id=task_id_to_uuid(task_input.task_id),
        trace_id=trace_id,
        instruction=task_input.user_text,
        context={
            "task_kind": task_input.task_kind,
            "route": task_input.route,
            "route_plan": task_input.route_plan,
            "requires_mcp": "true" if task_input.requires_mcp else "false",
            "candidate_capabilities_json": json.dumps(list(task_input.candidate_capabilities), ensure_ascii=False),
            "_task_id": task_input.task_id,
            "_thread_id": thread_id,
        },
    )


def context_weaver_output_to_task_result(
    agent_output: AgentOutput,
    *,
    task_id: str,
    agent_role: str,
) -> ContextWeaverTaskResult:
    """Map harness AgentOutput back to graph ContextWeaverTaskResult."""
    parsed: ContextWeaverOutput | None = None
    if isinstance(agent_output.output, ContextWeaverOutput):
        parsed = agent_output.output

    if agent_output.status == "failure":
        return ContextWeaverTaskResult(
            task_id=task_id,
            agent_role=agent_role,
            status="failure",
            confidence=agent_output.confidence,
            requires_review=True,
            output=None,
            error=agent_output.error_message or "context_weaver failed",
        )

    requires_review = agent_output.status == "partial"
    return ContextWeaverTaskResult(
        task_id=task_id,
        agent_role=agent_role,
        status=agent_output.status,
        confidence=agent_output.confidence,
        requires_review=requires_review,
        output=parsed,
        error=agent_output.error_message,
    )


def researcher_to_agent_input(
    task_input: ResearcherInput,
    *,
    trace_id: str,
    thread_id: str,
    user_id: str = "",
    org_id: str = "",
) -> AgentInput:
    """Build AgentInput for Researcher from graph node payload."""
    return AgentInput(
        task_id=task_id_to_uuid(task_input.task_id),
        trace_id=trace_id,
        instruction=task_input.context_packet.user_text,
        context={
            "context_packet_json": task_input.context_packet.model_dump_json(),
            "prior_context": task_input.prior_context or "",
            "mcp_tool_output_max_chars": str(task_input.mcp_tool_output_max_chars),
            "revision_feedback": task_input.revision_feedback or "",
            "_task_id": task_input.task_id,
            "_thread_id": thread_id,
            "_user_id": user_id,
            "_org_id": org_id,
        },
    )


def researcher_output_to_task_result(
    agent_output: AgentOutput,
    *,
    task_id: str,
    agent_role: str,
) -> ResearcherTaskResult:
    """Map harness AgentOutput back to graph ResearcherTaskResult."""
    from palatium_ai.application.agents.researcher.parsing import FAILURE_PLACEHOLDER_SUMMARY

    parsed: ResearcherOutput | None = None
    if isinstance(agent_output.output, ResearcherOutput) and (
        agent_output.status != "failure" or agent_output.output.summary != FAILURE_PLACEHOLDER_SUMMARY
    ):
        parsed = agent_output.output

    if agent_output.status == "failure":
        requires_review = agent_output.error_message != "MCP tool call denied by human approval"
        return ResearcherTaskResult(
            task_id=task_id,
            agent_role=agent_role,
            status="failure",
            confidence=agent_output.confidence,
            requires_review=requires_review,
            output=parsed,
            error=agent_output.error_message or "researcher failed",
        )

    requires_review = agent_output.status == "partial"
    return ResearcherTaskResult(
        task_id=task_id,
        agent_role=agent_role,
        status=agent_output.status,
        confidence=agent_output.confidence,
        requires_review=requires_review,
        output=parsed,
        error=agent_output.error_message,
    )


def coder_to_agent_input(
    task_input: CoderInput,
    *,
    trace_id: str,
    thread_id: str,
) -> AgentInput:
    """Build AgentInput for Coder from graph node payload."""
    return AgentInput(
        task_id=task_id_to_uuid(task_input.task_id),
        trace_id=trace_id,
        instruction=task_input.context_packet.user_text,
        context={
            "context_packet_json": task_input.context_packet.model_dump_json(),
            "revision_feedback": task_input.revision_feedback or "",
            "_task_id": task_input.task_id,
            "_thread_id": thread_id,
        },
    )


def coder_output_to_execution_result(
    agent_output: AgentOutput,
    *,
    task_id: str,
    agent_role: str,
) -> ResearcherTaskResult:
    """Map Coder AgentOutput into shared execution slot (ResearcherTaskResult)."""
    summary = "coder failed"
    confidence = agent_output.confidence
    sources: tuple[str, ...] = ()
    if isinstance(agent_output.output, CoderOutput):
        summary = agent_output.output.summary
        confidence = agent_output.output.confidence
        if agent_output.output.language:
            sources = (f"language:{agent_output.output.language}",)
        if agent_output.output.requires_sandbox_exec:
            sources = (*sources, "sandbox_exec_deferred")
    parsed = ResearcherOutput(summary=summary, confidence=confidence, sources_used=sources)
    if agent_output.status == "failure":
        return ResearcherTaskResult(
            task_id=task_id,
            agent_role=agent_role,
            status="failure",
            confidence=agent_output.confidence,
            requires_review=True,
            output=parsed,
            error=agent_output.error_message or "coder failed",
        )
    return ResearcherTaskResult(
        task_id=task_id,
        agent_role=agent_role,
        status=agent_output.status,
        confidence=agent_output.confidence,
        requires_review=agent_output.status == "partial",
        output=parsed,
        error=agent_output.error_message,
    )


def analyst_to_agent_input(
    task_input: AnalystInput,
    *,
    trace_id: str,
    thread_id: str,
) -> AgentInput:
    """Build AgentInput for Analyst from graph node payload."""
    return AgentInput(
        task_id=task_id_to_uuid(task_input.task_id),
        trace_id=trace_id,
        instruction=task_input.context_packet.user_text,
        context={
            "context_packet_json": task_input.context_packet.model_dump_json(),
            "revision_feedback": task_input.revision_feedback or "",
            "_task_id": task_input.task_id,
            "_thread_id": thread_id,
        },
    )


def analyst_output_to_execution_result(
    agent_output: AgentOutput,
    *,
    task_id: str,
    agent_role: str,
) -> ResearcherTaskResult:
    """Map Analyst AgentOutput into shared execution slot (ResearcherTaskResult)."""
    summary = "analyst failed"
    confidence = agent_output.confidence
    sources: tuple[str, ...] = ()
    if isinstance(agent_output.output, AnalystOutput):
        summary = agent_output.output.summary
        confidence = agent_output.output.confidence
        sources = agent_output.output.findings
    parsed = ResearcherOutput(summary=summary, confidence=confidence, sources_used=sources)
    if agent_output.status == "failure":
        return ResearcherTaskResult(
            task_id=task_id,
            agent_role=agent_role,
            status="failure",
            confidence=agent_output.confidence,
            requires_review=True,
            output=parsed,
            error=agent_output.error_message or "analyst failed",
        )
    return ResearcherTaskResult(
        task_id=task_id,
        agent_role=agent_role,
        status=agent_output.status,
        confidence=agent_output.confidence,
        requires_review=agent_output.status == "partial",
        output=parsed,
        error=agent_output.error_message,
    )


def memory_keeper_to_agent_input(
    task_input: MemoryKeeperInput,
    *,
    trace_id: str,
    thread_id: str,
) -> AgentInput:
    """Build AgentInput for MemoryKeeper from consolidation job payload."""
    return AgentInput(
        task_id=task_id_to_uuid(task_input.task_id),
        trace_id=trace_id,
        instruction=f"consolidate transcript for thread {task_input.thread_id}",
        context={
            "thread_id": task_input.thread_id,
            "transcript_excerpt": task_input.transcript_excerpt,
            "existing_memory_texts_json": json.dumps(
                list(task_input.existing_memory_texts),
                ensure_ascii=False,
            ),
            "_task_id": task_input.task_id,
            "_thread_id": thread_id,
        },
    )


def memory_keeper_output_to_task_result(
    agent_output: AgentOutput,
    *,
    task_id: str,
    agent_role: str,
) -> MemoryKeeperTaskResult:
    """Map harness AgentOutput back to MemoryKeeperTaskResult."""
    from palatium_ai.application.agents.memory_keeper.agent import LLM_STAGE_FAILURE

    parsed: MemoryKeeperOutput | None = None
    if isinstance(agent_output.output, MemoryKeeperOutput):
        parsed = agent_output.output

    if agent_output.error_message == LLM_STAGE_FAILURE:
        return MemoryKeeperTaskResult(
            task_id=task_id,
            agent_role=agent_role,
            status="success",
            confidence=agent_output.confidence,
            requires_review=False,
            output=parsed,
            error=agent_output.error_message,
        )

    return MemoryKeeperTaskResult(
        task_id=task_id,
        agent_role=agent_role,
        status=agent_output.status,
        confidence=agent_output.confidence,
        requires_review=False,
        output=parsed,
        error=agent_output.error_message,
    )


def text_ingestor_to_agent_input(
    task_input: TextIngestorInput,
    *,
    trace_id: str,
    thread_id: str,
) -> AgentInput:
    """Build AgentInput for TextIngestor from ingest job payload."""
    context: dict[str, str] = {
        "task_id": task_input.task_id,
        "thread_id": task_input.thread_id,
        "raw_text": task_input.raw_text,
        "max_chunk_chars": str(task_input.max_chunk_chars),
        "enrich_context_prefix": "true" if task_input.enrich_context_prefix else "false",
        "_task_id": task_input.task_id,
        "_thread_id": thread_id,
    }
    if task_input.document_id:
        context["document_id"] = task_input.document_id
    if task_input.mime_type:
        context["mime_type"] = task_input.mime_type
    if task_input.locale:
        context["locale"] = task_input.locale
    if task_input.document_title:
        context["document_title"] = task_input.document_title
    return AgentInput(
        task_id=task_id_to_uuid(task_input.task_id),
        trace_id=trace_id,
        instruction=f"prepare document chunks for thread {task_input.thread_id}",
        context=context,
    )


def text_ingestor_output_to_task_result(
    agent_output: AgentOutput,
    *,
    task_id: str,
    agent_role: str,
) -> TextIngestorTaskResult:
    """Map harness AgentOutput back to TextIngestorTaskResult."""
    from palatium_ai.application.agents.text_ingestor.agent import CONTEXT_PREFIX_STAGE_FAILURE

    parsed: TextIngestorOutput | None = None
    if isinstance(agent_output.output, TextIngestorOutput):
        parsed = agent_output.output

    if agent_output.status == "failure":
        return TextIngestorTaskResult(
            task_id=task_id,
            agent_role=agent_role,
            status="failure",
            confidence=agent_output.confidence,
            requires_review=True,
            output=parsed,
            error=agent_output.error_message or "text_ingestor failed",
        )

    requires_review = agent_output.status == "partial"
    if agent_output.error_message == CONTEXT_PREFIX_STAGE_FAILURE and parsed is not None:
        requires_review = False
    return TextIngestorTaskResult(
        task_id=task_id,
        agent_role=agent_role,
        status=agent_output.status,
        confidence=agent_output.confidence,
        requires_review=requires_review,
        output=parsed,
        error=agent_output.error_message,
    )

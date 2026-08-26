# src/palatium_ai/application/orchestration/node_inputs.py

"""Фабрики входных DTO для узлов StateGraph."""

from __future__ import annotations

from typing import TYPE_CHECKING

from palatium_ai.application.orchestration import selectors
from palatium_ai.domain.agents.context_weaver import ContextWeaverInput
from palatium_ai.domain.agents.critic import CriticInput
from palatium_ai.domain.agents.formatter import FormatterInput
from palatium_ai.domain.agents.researcher import ResearcherInput
from palatium_ai.domain.agents.supervisor import SupervisorInput

if TYPE_CHECKING:
    from palatium_ai.application.orchestration.snapshot import OrchestrationSnapshot
    from palatium_ai.application.orchestration.state import AgentGraphState


def build_supervisor_input(snapshot: OrchestrationSnapshot) -> SupervisorInput:
    """Собирает вход для Supervisor."""
    return SupervisorInput(
        task_id=snapshot.task_id,
        user_text=snapshot.user_text,
        task_kind=snapshot.task_kind,
        requires_mcp=snapshot.requires_mcp,
        candidate_capabilities=snapshot.candidate_capabilities,
        classification_confidence=snapshot.classification.confidence,
    )


def build_context_weaver_input(snapshot: OrchestrationSnapshot) -> ContextWeaverInput:
    """Собирает вход для ContextWeaver."""
    return ContextWeaverInput(
        task_id=snapshot.task_id,
        user_text=snapshot.user_text,
        task_kind=snapshot.task_kind,
        route=snapshot.route,
        route_plan=snapshot.route_plan,
        requires_mcp=snapshot.requires_mcp,
        candidate_capabilities=snapshot.candidate_capabilities,
    )


def build_researcher_input(
    snapshot: OrchestrationSnapshot,
    state: AgentGraphState,
) -> ResearcherInput:
    """Собирает вход для Researcher."""
    return ResearcherInput(
        task_id=snapshot.task_id,
        context_packet=snapshot.context_packet(
            state,
            fallback_strategy="reason_only",
            fallback_rationale="Researcher requires a context packet before execution.",
        ),
        prior_context=selectors.resolved_prior_assistant_content(state),
        mcp_tool_output_max_chars=selectors.prompt_budget(state).mcp_tool_output_max_chars,
        revision_feedback=selectors.resolved_revision_feedback(state),
    )


def build_critic_input(
    snapshot: OrchestrationSnapshot,
    state: AgentGraphState,
) -> CriticInput:
    """Собирает вход для Critic."""
    return CriticInput(
        task_id=snapshot.task_id,
        context_packet=snapshot.context_packet(
            state,
            fallback_strategy=snapshot.selected_strategy,
            fallback_rationale="Fallback packet synthesized by graph before critic execution.",
        ),
        classification_confidence=snapshot.classification.confidence,
        classification_reasoning=snapshot.classification_reasoning,
        worker_summary=snapshot.worker_summary,
        selected_strategy=snapshot.selected_strategy,
        continuation_kind=selectors.resolved_continuation_kind(state),
        user_input_chars=len(selectors.resolved_user_text(state)),
    )


def build_formatter_input(
    snapshot: OrchestrationSnapshot,
    state: AgentGraphState,
) -> FormatterInput:
    """Собирает вход для Formatter (HITL только от Critic + non-suppressed Intent)."""
    critic_result = state.get("critic")
    critic_requires_review = critic_result.requires_review if critic_result is not None else False
    intent_review = snapshot.classification.requires_review and not selectors.suppress_intent_hitl(state)

    return FormatterInput(
        task_id=snapshot.task_id,
        context_packet=snapshot.context_packet(
            state,
            fallback_strategy="clarify" if snapshot.route == "clarification" else "format_only",
            fallback_rationale="Fallback packet synthesized by graph before formatter execution.",
        ),
        worker_summary=snapshot.worker_summary,
        critic_summary=snapshot.critic_summary,
        requires_review=intent_review or critic_requires_review,
        requires_user_choice=selectors.requires_user_choice(state),
        revision_feedback=selectors.resolved_revision_feedback(state),
    )

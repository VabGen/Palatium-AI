# src/palatium_ai/application/agents/researcher/outcomes.py

"""Shared AgentOutput helpers for Researcher paths."""

from __future__ import annotations

from uuid import UUID

from palatium_ai.application.agents.researcher.parsing import FAILURE_PLACEHOLDER_SUMMARY
from palatium_ai.domain.agents.messages import AgentOutput
from palatium_ai.domain.agents.researcher import ResearcherOutput


def failure_output(
    task_id: UUID,
    *,
    summary: str | None,
    error: str,
) -> AgentOutput:
    if summary is not None:
        output = ResearcherOutput(summary=summary, confidence=0.0, sources_used=())
    else:
        output = ResearcherOutput(
            summary=FAILURE_PLACEHOLDER_SUMMARY,
            confidence=0.0,
            sources_used=(),
        )
    return AgentOutput(
        task_id=task_id,
        status="failure",
        confidence=0.0,
        output=output,
        error_message=error,
    )


def soft_empty_output(task_id: UUID, *, error: str) -> AgentOutput:
    """Empty MCP hits — soft partial, not a hard worker failure (no synthesis)."""
    return AgentOutput(
        task_id=task_id,
        status="partial",
        confidence=0.0,
        output=ResearcherOutput(
            summary=FAILURE_PLACEHOLDER_SUMMARY,
            confidence=0.0,
            sources_used=(),
        ),
        error_message=error,
    )


def required_empty_clarification_output(task_id: UUID, *, question: str) -> AgentOutput:
    """Adaptive grounding required + empty retrieval → ask user for the missing source."""
    from palatium_ai.domain.agents.researcher import GROUNDING_REQUIRED_EMPTY
    from palatium_ai.domain.policies.grounding import GroundingPolicy

    text = question.strip() or GroundingPolicy.required_empty_clarification(None)
    return AgentOutput(
        task_id=task_id,
        status="partial",
        confidence=0.0,
        output=ResearcherOutput(
            summary=text,
            confidence=0.0,
            sources_used=(),
            grounding_satisfied=False,
            grounding_degraded=True,
            cannot_answer_without_source=True,
        ),
        error_message=GROUNDING_REQUIRED_EMPTY,
    )

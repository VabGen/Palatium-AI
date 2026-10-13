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

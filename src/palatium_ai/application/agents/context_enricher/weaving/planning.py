# src/palatium_ai/application/agents/context_enricher/weaving/planning.py

"""Execution planning helpers for weaving phase."""

from __future__ import annotations

from palatium_ai.domain.agents.context_weaver import ContextWeaverInput
from palatium_ai.domain.mcp.models import ExecutionStrategy


def build_context_summary(
    task_input: ContextWeaverInput,
    selected_strategy: ExecutionStrategy,
) -> str:
    capabilities = ", ".join(task_input.candidate_capabilities) if task_input.candidate_capabilities else "none"
    return (
        f"task_kind={task_input.task_kind}; route={task_input.route}; "
        f"capabilities={capabilities}; strategy={selected_strategy}"
    )

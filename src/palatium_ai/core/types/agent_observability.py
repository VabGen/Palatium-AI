# src/palatium_ai/core/types/agent_observability.py

"""Closed label sets for agent handoff / worker-execution metrics (040, W5.5).

Emitted by ``route_after_*`` and worker nodes; evals assert observed labels ⊆ these
frozensets so cardinality does not drift into free-form strings.
"""

from __future__ import annotations

from typing import Final, Literal, get_args

#: Reasons recorded on ``palatium_agent_handoffs_total{reason}``.
#: Includes fixed edge reasons plus ``ExecutionStrategy`` values used as reason.
AgentHandoffReason = Literal[
    "requires_clarification",
    "strategy_clarify",
    "format_only",
    "parallel_workers",
    "default_critic",
    "terminal_mcp_failure",
    "requires_review",
    "requires_review_parallel",
    "finalize",
    "researcher",
    "direct_tool_call",
    "retrieve_then_reason",
    "reason_only",
    "code_sandbox",
    "data_analysis",
    "ack_only",
    "clarify",
    "unspecified",
]

#: Statuses on ``palatium_worker_execution_total{status}`` (TaskResult.status).
WorkerExecutionStatus = Literal["success", "failure", "partial", "unspecified"]

AGENT_HANDOFF_REASONS: Final[frozenset[str]] = frozenset(get_args(AgentHandoffReason))
WORKER_EXECUTION_STATUSES: Final[frozenset[str]] = frozenset(get_args(WorkerExecutionStatus))


def coerce_handoff_reason(reason: str | None) -> AgentHandoffReason:
    """Map free-form reason to the closed set (unknown → unspecified)."""
    value = (reason or "").strip()
    if value in AGENT_HANDOFF_REASONS:
        return value  # type: ignore[return-value]
    return "unspecified"


def coerce_worker_status(status: str | None) -> WorkerExecutionStatus:
    """Map free-form status to the closed set (unknown → unspecified)."""
    value = (status or "").strip()
    if value in WORKER_EXECUTION_STATUSES:
        return value  # type: ignore[return-value]
    return "unspecified"


__all__ = [
    "AGENT_HANDOFF_REASONS",
    "WORKER_EXECUTION_STATUSES",
    "AgentHandoffReason",
    "WorkerExecutionStatus",
    "coerce_handoff_reason",
    "coerce_worker_status",
]

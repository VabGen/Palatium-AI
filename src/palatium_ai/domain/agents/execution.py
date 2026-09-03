# src/palatium_ai/domain/agents/execution.py

"""Re-export execution strategy (+ worker routing set) for agent layer."""

from __future__ import annotations

from palatium_ai.domain.mcp.models import ExecutionStrategy

CLARIFY_STRATEGY: ExecutionStrategy = "clarify"

WORKER_STRATEGIES: frozenset[ExecutionStrategy] = frozenset(
    {
        "direct_tool_call",
        "retrieve_then_reason",
        "reason_only",
        "code_sandbox",
        "data_analysis",
    }
)

RESEARCHER_STRATEGIES: frozenset[ExecutionStrategy] = frozenset(
    {
        "direct_tool_call",
        "retrieve_then_reason",
        "reason_only",
    }
)

CODER_STRATEGIES: frozenset[ExecutionStrategy] = frozenset({"code_sandbox"})
ANALYST_STRATEGIES: frozenset[ExecutionStrategy] = frozenset({"data_analysis"})

__all__ = [
    "ExecutionStrategy",
    "WORKER_STRATEGIES",
    "RESEARCHER_STRATEGIES",
    "CODER_STRATEGIES",
    "ANALYST_STRATEGIES",
    "CLARIFY_STRATEGY",
]

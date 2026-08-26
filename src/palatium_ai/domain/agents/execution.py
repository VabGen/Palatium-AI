# src/palatium_ai/domain/agents/execution.py

"""Re-export execution strategy (+ worker routing set) for agent layer."""

from __future__ import annotations

from palatium_ai.domain.mcp.models import ExecutionStrategy

WORKER_STRATEGIES: frozenset[ExecutionStrategy] = frozenset(
    {
        "direct_tool_call",
        "retrieve_then_reason",
        "reason_only",
    }
)

__all__ = ["ExecutionStrategy", "WORKER_STRATEGIES"]

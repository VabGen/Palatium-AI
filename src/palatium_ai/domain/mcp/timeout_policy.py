# src/palatium_ai/domain/mcp/timeout_policy.py

"""MCP per-tool timeout invariants (070): every tool must answer before its agent dies."""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from dataclasses import dataclass

_DEFAULT_KEY = "default"
_MCP_TOOL_PREFIX = "mcp:"


class McpTimeoutBudgetError(RuntimeError):
    """Raised when an MCP timeout is not strictly below the calling agent's budget."""


@dataclass(frozen=True, slots=True)
class McpAgentBudget:
    """One MCP-capable agent: its wall-clock budget and the MCP tools it may call."""

    name: str
    timeout_seconds: int
    tools: frozenset[str]


def mcp_tool_keys(allowed_tools: Iterable[str]) -> frozenset[str]:
    """Extract ``server.tool`` keys from ``AgentConfig.allowed_tools`` (``mcp:<server>.<tool>``)."""
    keys: set[str] = set()
    for raw in allowed_tools:
        text = raw.strip()
        if not text.startswith(_MCP_TOOL_PREFIX):
            continue
        key = text[len(_MCP_TOOL_PREFIX) :].strip()
        if key:
            keys.add(key)
    return frozenset(keys)


def _matches(key: str, agent_tool: str) -> bool:
    """Config key specificity: ``server.tool`` exact, bare ``tool`` matches any server."""
    if key == agent_tool:
        return True
    if "." not in key:
        return agent_tool.rsplit(".", 1)[-1] == key
    return False


def assert_tool_timeouts_within_agent_budget(
    *,
    default_timeout_seconds: int,
    tool_timeouts: Mapping[str, int],
    agent_budgets: Iterable[McpAgentBudget],
) -> None:
    """Fail startup when an MCP timeout >= the budget of the agent that calls it (070).

    A tool allowed to hang longer than the agent awaiting it makes the agent die first
    and drop the (successful) tool result. The generic ``default_timeout_seconds`` applies
    to every tool, so it is checked against the tightest MCP-capable agent.
    """
    budgets = [budget for budget in agent_budgets if budget.tools]
    if not budgets:
        return

    ceiling = min(budget.timeout_seconds for budget in budgets)
    offenders: dict[str, str] = {}
    if default_timeout_seconds >= ceiling:
        tightest = min(budgets, key=lambda budget: budget.timeout_seconds)
        offenders[_DEFAULT_KEY] = f"{default_timeout_seconds}s >= {tightest.name} {ceiling}s"

    for key, seconds in tool_timeouts.items():
        if key == _DEFAULT_KEY:
            continue
        callers = [budget for budget in budgets if any(_matches(key, tool) for tool in budget.tools)]
        if not callers:
            continue
        limit = min(budget.timeout_seconds for budget in callers)
        if seconds >= limit:
            tightest = min(callers, key=lambda budget: budget.timeout_seconds)
            offenders[key] = f"{seconds}s >= {tightest.name} {limit}s"

    if not offenders:
        return
    detail = "; ".join(f"{name}: {reason}" for name, reason in sorted(offenders.items()))
    raise McpTimeoutBudgetError(
        "MCP tool timeouts must be < the calling AgentConfig.timeout_seconds; violations — " + detail,
    )

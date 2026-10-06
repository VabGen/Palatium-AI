# src/palatium_ai/application/services/execution_planner.py

"""ExecutionPlanner строит execution bundle из нормализованного context packet."""

from __future__ import annotations

from typing import TYPE_CHECKING

from palatium_ai.application.services.mcp_capabilities import MCPCapabilityIndex
from palatium_ai.domain.agents.context_weaver import ContextWeaverInput
from palatium_ai.domain.agents.workflow_policy import WorkflowExecutionPolicy
from palatium_ai.domain.mcp.discovery_policy import McpDiscoveryPolicy
from palatium_ai.domain.mcp.models import ExecutionPlanBundle, ToolExecutionPlan
from palatium_ai.domain.policies.parallel_workers import ParallelWorkerPolicy
from palatium_ai.domain.policies.types import TaskKind

if TYPE_CHECKING:
    from palatium_ai.domain.agents.supervisor import WorkerRoute

_CODE_CAPS: frozenset[str] = frozenset({"code", "coding", "sandbox", "code_exec"})
_ANALYST_CAPS: frozenset[str] = frozenset({"analytics", "analysis", "metrics", "trends", "stats", "statistics"})
_KNOWLEDGE_KINDS: frozenset[TaskKind] = frozenset({"knowledge_request", "tool_execution"})


class ExecutionPlanner:
    """Отдельный planner, чтобы orchestration не зависел от реализации агента."""

    def __init__(self, capability_index: MCPCapabilityIndex | None = None) -> None:
        self._capability_index = capability_index

    async def build(self, task_input: ContextWeaverInput) -> ExecutionPlanBundle:
        """Возвращает execution bundle; multi-step when research∥analyst (P2.15)."""
        if task_input.route in {"clarification", "formatter"}:
            primary = await self._build_primary_step(task_input)
            return ExecutionPlanBundle(
                selected_strategy=primary.strategy,
                requires_tool_call=primary.requires_tool_call,
                steps=(primary,),
            )

        parallel = ParallelWorkerPolicy.decide_from_capabilities(
            candidate_capabilities=task_input.candidate_capabilities,
        )
        if parallel.parallel:
            research_step = await self._build_research_step(task_input)
            analyst_step = ToolExecutionPlan(
                strategy="data_analysis",
                requires_tool_call=False,
                rationale=(
                    f"Parallel multi-capability plan ({parallel.reason}): "
                    "structured analysis alongside knowledge retrieval."
                ),
            )
            return ExecutionPlanBundle(
                selected_strategy=research_step.strategy,
                requires_tool_call=research_step.requires_tool_call or analyst_step.requires_tool_call,
                steps=(research_step, analyst_step),
            )

        primary_step = await self._build_primary_step(task_input)
        return ExecutionPlanBundle(
            selected_strategy=primary_step.strategy,
            requires_tool_call=primary_step.requires_tool_call,
            steps=(primary_step,),
        )

    async def _build_research_step(self, task_input: ContextWeaverInput) -> ToolExecutionPlan:
        """Knowledge/MCP path without analytics/code short-circuit (parallel half)."""
        discovered = await self._try_discovered_mcp(task_input)
        if discovered is not None:
            return discovered

        executable_kind = WorkflowExecutionPolicy.executable_task_kind(
            task_input.task_kind,
            requires_mcp=task_input.requires_mcp,
        )
        if task_input.requires_mcp:
            return _mcp_unresolved_plan()
        if task_input.has_attachment_context:
            return _attachment_grounded_plan(
                "Parallel research half: fenced attachment text already present; ground without search_knowledge."
            )
        return _search_knowledge_plan(
            f"Parallel research half: retrieve via platform.search_knowledge "
            f"then reason (executable_kind={executable_kind})."
        )

    async def _build_primary_step(self, task_input: ContextWeaverInput) -> ToolExecutionPlan:
        executable_kind = WorkflowExecutionPolicy.executable_task_kind(
            task_input.task_kind,
            requires_mcp=task_input.requires_mcp,
        )

        route_plan = _route_local_plan(task_input.route, executable_kind, task_input.requires_mcp)
        if route_plan is not None:
            return route_plan

        discovered = await self._try_discovered_mcp(task_input)
        if discovered is not None:
            return discovered

        cap_plan = _capability_hint_plan(task_input.candidate_capabilities)
        if cap_plan is not None:
            return cap_plan

        if executable_kind in _KNOWLEDGE_KINDS:
            return _knowledge_or_tool_plan(task_input, executable_kind)

        return ToolExecutionPlan(
            strategy="reason_only",
            requires_tool_call=False,
            rationale="No external tool required; worker can reason over current context.",
        )

    async def _try_discovered_mcp(self, task_input: ContextWeaverInput) -> ToolExecutionPlan | None:
        mcp_gate = McpDiscoveryPolicy.should_discover_capabilities(
            requires_mcp=task_input.requires_mcp,
            route=task_input.route,
        )
        if not mcp_gate.allowed or self._capability_index is None:
            return None
        binding = await self._capability_index.resolve_best(
            task_text=task_input.user_text,
            requested_capabilities=task_input.candidate_capabilities,
        )
        if binding is None:
            return None
        return ToolExecutionPlan(
            strategy="direct_tool_call",
            capability=binding.capability,
            server_name=binding.server_name,
            tool_name=binding.tool_name,
            requires_tool_call=True,
            rationale="Matching MCP capability was discovered from registered tool descriptors.",
        )


def _route_local_plan(
    route: WorkerRoute,
    executable_kind: TaskKind,
    requires_mcp: bool,
) -> ToolExecutionPlan | None:
    if route == "clarification":
        return ToolExecutionPlan(
            strategy="clarify",
            requires_tool_call=False,
            rationale="Supervisor marked the request as needing clarification.",
        )
    if route != "formatter":
        return None
    # Social → Formatter LLM (format_only). Canned ack_only templates are a 2024-era
    # latency shortcut that fails closed wrongly when Intent mislabels a real ask (055).
    # Fast-tier LLM for phatic is the 2026 default; keep ack_only only as an explicit
    # eval/cassette strategy, not the live planner path.
    if executable_kind == "social_conversation" and not requires_mcp:
        return ToolExecutionPlan(
            strategy="format_only",
            requires_tool_call=False,
            rationale="Phatic/social turn; Formatter LLM reply (no canned ack template).",
        )
    return ToolExecutionPlan(
        strategy="format_only",
        requires_tool_call=False,
        rationale="Task can be completed by formatting already available data.",
    )


def _capability_hint_plan(candidate_capabilities: tuple[str, ...]) -> ToolExecutionPlan | None:
    caps = {c.strip().lower() for c in candidate_capabilities}
    if caps & _CODE_CAPS:
        return ToolExecutionPlan(
            strategy="code_sandbox",
            requires_tool_call=False,
            rationale="Capability hints request a code draft/plan (sandbox exec remains HITL-gated).",
        )
    if caps & _ANALYST_CAPS:
        return ToolExecutionPlan(
            strategy="data_analysis",
            requires_tool_call=False,
            rationale="Capability hints request structured analysis without tool execution.",
        )
    return None


def _knowledge_or_tool_plan(
    task_input: ContextWeaverInput,
    executable_kind: TaskKind,
) -> ToolExecutionPlan:
    if task_input.has_attachment_context:
        return _attachment_grounded_plan(
            "Turn already carries fenced attachment text; ground the answer on upload OCR without search_knowledge."
        )
    if task_input.requires_mcp:
        return _mcp_unresolved_plan()
    return _search_knowledge_plan(
        "Knowledge path without domain MCP binding: retrieve via "
        "platform.search_knowledge then reason "
        f"(executable_kind={executable_kind})."
    )


def _attachment_grounded_plan(rationale: str) -> ToolExecutionPlan:
    return ToolExecutionPlan(
        strategy="reason_only",
        requires_tool_call=False,
        rationale=rationale,
    )


def _mcp_unresolved_plan() -> ToolExecutionPlan:
    return ToolExecutionPlan(
        strategy="reason_only",
        requires_tool_call=False,
        rationale=(
            "requires_mcp=true but no MCP capability resolved; "
            "worker must fail closed instead of inventing tool results."
        ),
    )


def _search_knowledge_plan(rationale: str) -> ToolExecutionPlan:
    return ToolExecutionPlan(
        strategy="retrieve_then_reason",
        capability="knowledge",
        server_name="platform",
        tool_name="search_knowledge",
        requires_tool_call=True,
        rationale=rationale,
    )

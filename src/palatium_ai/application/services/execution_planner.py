# src/palatium_ai/application/services/execution_planner.py

"""ExecutionPlanner строит execution bundle из нормализованного context packet."""

from __future__ import annotations

from palatium_ai.application.services.mcp_capabilities import MCPCapabilityIndex
from palatium_ai.domain.agents.context_weaver import ContextWeaverInput
from palatium_ai.domain.agents.workflow_policy import WorkflowExecutionPolicy
from palatium_ai.domain.mcp.discovery_policy import McpDiscoveryPolicy
from palatium_ai.domain.mcp.models import ExecutionPlanBundle, ToolExecutionPlan


class ExecutionPlanner:
    """Отдельный planner, чтобы orchestration не зависел от реализации агента."""

    def __init__(self, capability_index: MCPCapabilityIndex | None = None) -> None:
        self._capability_index = capability_index

    async def build(self, task_input: ContextWeaverInput) -> ExecutionPlanBundle:
        """Возвращает однотипный execution bundle для текущего запроса."""
        primary_step = await self._build_primary_step(task_input)
        return ExecutionPlanBundle(
            selected_strategy=primary_step.strategy,
            requires_tool_call=primary_step.requires_tool_call,
            steps=(primary_step,),
        )

    async def _build_primary_step(self, task_input: ContextWeaverInput) -> ToolExecutionPlan:
        executable_kind = WorkflowExecutionPolicy.executable_task_kind(
            task_input.task_kind,
            requires_mcp=task_input.requires_mcp,
        )

        if task_input.route == "clarification":
            return ToolExecutionPlan(
                strategy="clarify",
                requires_tool_call=False,
                rationale="Supervisor marked the request as needing clarification.",
            )

        if task_input.route == "formatter":
            if executable_kind == "social_conversation" and not task_input.requires_mcp:
                return ToolExecutionPlan(
                    strategy="ack_only",
                    requires_tool_call=False,
                    rationale="Phatic/social turn; direct Formatter reply without retrieval.",
                )
            return ToolExecutionPlan(
                strategy="format_only",
                requires_tool_call=False,
                rationale="Task can be completed by formatting already available data.",
            )

        mcp_gate = McpDiscoveryPolicy.should_discover_capabilities(
            requires_mcp=task_input.requires_mcp,
            route=task_input.route,
        )
        if mcp_gate.allowed and self._capability_index is not None:
            binding = await self._capability_index.resolve_best(
                task_text=task_input.user_text,
                requested_capabilities=task_input.candidate_capabilities,
            )
            if binding is not None:
                return ToolExecutionPlan(
                    strategy="direct_tool_call",
                    capability=binding.capability,
                    server_name=binding.server_name,
                    tool_name=binding.tool_name,
                    requires_tool_call=True,
                    rationale="Matching MCP capability was discovered from registered tool descriptors.",
                )

        if executable_kind in {"knowledge_request", "tool_execution"}:
            if task_input.requires_mcp:
                return ToolExecutionPlan(
                    strategy="reason_only",
                    requires_tool_call=False,
                    rationale=(
                        "requires_mcp=true but no MCP capability resolved; "
                        "worker must fail closed instead of inventing tool results."
                    ),
                )
            return ToolExecutionPlan(
                strategy="retrieve_then_reason",
                requires_tool_call=False,
                rationale=(
                    "No suitable MCP tool was resolved; single-pass research/reasoning "
                    f"(executable_kind={executable_kind})."
                ),
            )

        return ToolExecutionPlan(
            strategy="reason_only",
            requires_tool_call=False,
            rationale="No external tool required; worker can reason over current context.",
        )

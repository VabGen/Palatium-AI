# src/palatium_ai/application/agents/context_enricher/weaving/agent.py

"""Weaving phase — BaseAgent (post-supervisor context packet + execution plan, 055)."""

from __future__ import annotations

from typing import TYPE_CHECKING, Literal

from palatium_ai.application.agents.context_enricher.weaving.config import CLARIFY_CONFIDENCE, PLANNED_CONFIDENCE
from palatium_ai.application.agents.context_enricher.weaving.parsing import decode_context_weaver_input
from palatium_ai.application.agents.context_enricher.weaving.planning import build_context_summary
from palatium_ai.application.services.execution_planner import ExecutionPlanner
from palatium_ai.application.services.mcp_capabilities import MCPCapabilityIndex
from palatium_ai.core.logging import get_logger
from palatium_ai.core.observability.metrics import agent_metrics
from palatium_ai.core.observability.tracing import traceable
from palatium_ai.domain.agents.base import BaseAgent
from palatium_ai.domain.agents.context_packet import ContextPacket
from palatium_ai.domain.agents.context_weaver import ContextWeaverOutput
from palatium_ai.domain.agents.execution import CLARIFY_STRATEGY
from palatium_ai.domain.agents.messages import AgentInput, AgentOutput
from palatium_ai.domain.ports.harness import HarnessPort

if TYPE_CHECKING:
    from palatium_ai.domain.agents.agent_config import AgentConfig
    from palatium_ai.domain.ports.mcp import MCPRegistryPort

logger = get_logger(__name__)


class ContextWeaverAgent(BaseAgent):
    """Builds context packet and execution plan before worker execution."""

    def __init__(
        self,
        harness: HarnessPort,
        config: AgentConfig,
        mcp_registry: MCPRegistryPort | None = None,
        *,
        capability_index: MCPCapabilityIndex | None = None,
    ) -> None:
        super().__init__(harness, config)
        if capability_index is not None:
            self._capability_index: MCPCapabilityIndex | None = capability_index
        elif mcp_registry is not None:
            self._capability_index = MCPCapabilityIndex(mcp_registry)
        else:
            self._capability_index = None
        self._execution_planner = ExecutionPlanner(self._capability_index)

    @property
    def config(self) -> AgentConfig:
        return self._config

    def get_required_context_keys(self) -> list[str]:
        return [
            "task_kind",
            "route",
            "route_plan",
            "requires_mcp",
            "candidate_capabilities_json",
        ]

    def get_available_tools(self) -> list[str]:
        return []

    @traceable(name="context_enricher.weaving.run")
    async def run(self, input: AgentInput) -> AgentOutput:
        agent_metrics.record_node_execution(self._config.role, "weaving")
        task_input = decode_context_weaver_input(input.context, instruction=input.instruction)

        try:
            execution_bundle = await self._execution_planner.build(task_input)
        except Exception:
            logger.exception("execution planner failed", task_id=str(input.task_id))
            agent_metrics.record_error(self._config.role, "weaving_planner_failure")
            return AgentOutput(
                task_id=input.task_id,
                status="failure",
                confidence=0.0,
                output=_empty_weaver_output(),
                error_message="execution plan could not be built",
            )

        if not execution_bundle.steps:
            logger.error("execution planner returned empty steps", task_id=str(input.task_id))
            agent_metrics.record_error(self._config.role, "weaving_empty_plan")
            return AgentOutput(
                task_id=input.task_id,
                status="failure",
                confidence=0.0,
                output=_empty_weaver_output(),
                error_message="execution plan has no steps",
            )

        execution_plan = execution_bundle.steps[0]
        context_summary = build_context_summary(task_input, execution_bundle.selected_strategy)
        context_packet = ContextPacket(
            task_id=task_input.task_id,
            user_text=task_input.user_text,
            task_kind=task_input.task_kind,
            route=task_input.route,
            route_plan=task_input.route_plan,
            requires_mcp=task_input.requires_mcp,
            candidate_capabilities=task_input.candidate_capabilities,
            execution_plan=execution_plan,
            context_summary=context_summary,
        )
        output = ContextWeaverOutput(
            context_packet=context_packet,
            execution_bundle=execution_bundle,
            available_capabilities=task_input.candidate_capabilities,
        )

        requires_review = execution_plan.strategy == CLARIFY_STRATEGY
        status: Literal["success", "failure", "partial"] = "partial" if requires_review else "success"
        confidence = CLARIFY_CONFIDENCE if requires_review else PLANNED_CONFIDENCE

        return AgentOutput(
            task_id=input.task_id,
            status=status,
            confidence=confidence,
            output=output,
        )


def _empty_weaver_output() -> ContextWeaverOutput:
    from palatium_ai.domain.mcp.models import ExecutionPlanBundle, ToolExecutionPlan

    placeholder_plan = ToolExecutionPlan(
        strategy="reason_only",
        requires_tool_call=False,
        rationale="placeholder",
    )
    packet = ContextPacket(
        task_id="placeholder",
        user_text="placeholder",
        task_kind="knowledge_request",
        route="researcher",
        route_plan="n/a",
        requires_mcp=False,
        candidate_capabilities=(),
        execution_plan=placeholder_plan,
        context_summary="n/a",
    )
    return ContextWeaverOutput(
        context_packet=packet,
        execution_bundle=ExecutionPlanBundle(
            selected_strategy="reason_only",
            requires_tool_call=False,
            steps=(placeholder_plan,),
        ),
        available_capabilities=(),
    )

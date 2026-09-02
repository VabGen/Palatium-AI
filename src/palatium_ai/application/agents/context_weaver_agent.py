# src/palatium_ai/application/agents/context_weaver_agent.py

"""Агент ContextWeaver — собирает execution plan и контекст для worker layer."""

from __future__ import annotations

import logging

from typing import TYPE_CHECKING, Literal

from palatium_ai.application.services.execution_planner import ExecutionPlanner
from palatium_ai.application.services.mcp_capabilities import MCPCapabilityIndex
from palatium_ai.core.observability.metrics import agent_metrics
from palatium_ai.core.observability.tracing import traceable
from palatium_ai.domain.agents.agent_config import AgentConfig
from palatium_ai.domain.agents.context_packet import ContextPacket
from palatium_ai.domain.agents.context_weaver import (
    ContextWeaverInput,
    ContextWeaverOutput,
    ContextWeaverTaskResult,
)
from palatium_ai.domain.agents.execution import CLARIFY_STRATEGY
from palatium_ai.domain.mcp.models import ExecutionStrategy

if TYPE_CHECKING:
    from palatium_ai.domain.agents.contracts import AgentContext
    from palatium_ai.domain.ports.mcp import MCPRegistryPort

logger = logging.getLogger(__name__)

CONTEXT_WEAVER_CONFIG = AgentConfig(
    name="context_weaver",
    role="context_weaver",
    model_tier="small",
    temperature=0.0,
    allowed_tools=(),
    timeout_seconds=30,
    max_retries=1,
    confidence_threshold=0.7,
)

# Confidence без LLM-оценок: детерминированная сборка => полная уверенность,
# clarify-маршрут => половина (downstream видит, что план требует человека).
_PLANNED_CONFIDENCE = 1.0
_CLARIFY_CONFIDENCE = 0.5


class ContextWeaverAgent:
    """Собирает контекст и execution plan до worker execution.

    Контракт отказного пути — как у остальных агентов: отказ планировщика
    конвертируется в failure-result с requires_review=True, исключения
    не покидают execute. LLM здесь нет, но planner/capability index —
    это IO с внешним состоянием и умеет падать.
    """

    config = CONTEXT_WEAVER_CONFIG

    def __init__(
        self,
        mcp_registry: MCPRegistryPort | None = None,
        *,
        capability_index: MCPCapabilityIndex | None = None,
    ) -> None:
        if capability_index is not None:
            self._capability_index: MCPCapabilityIndex | None = capability_index
        elif mcp_registry is not None:
            self._capability_index = MCPCapabilityIndex(mcp_registry)
        else:
            self._capability_index = None
        self._execution_planner = ExecutionPlanner(self._capability_index)

    @traceable(name="context_weaver.execute")
    async def execute(
        self,
        task_input: ContextWeaverInput,
        context: AgentContext,
    ) -> ContextWeaverTaskResult:
        """Собирает execution plan без сайд-эффектов."""
        _ = context
        agent_metrics.record_node_execution("context_weaver", "context_weaver_node")

        try:
            execution_bundle = await self._execution_planner.build(task_input)
        except Exception:
            logger.exception("execution planner failed (task=%s)", task_input.task_id)
            agent_metrics.record_error("context_weaver", "planner_failure")
            return ContextWeaverTaskResult(
                task_id=task_input.task_id,
                agent_role=self.config.role,
                status="failure",
                confidence=0.0,
                requires_review=True,
                output=None,
                error="execution plan could not be built",
            )

        if not execution_bundle.steps:
            logger.error("execution planner returned empty steps (task=%s)", task_input.task_id)
            agent_metrics.record_error("context_weaver", "empty_plan")
            return ContextWeaverTaskResult(
                task_id=task_input.task_id,
                agent_role=self.config.role,
                status="failure",
                confidence=0.0,
                requires_review=True,
                output=None,
                error="execution plan has no steps",
            )

        execution_plan = execution_bundle.steps[0]
        context_summary = _build_context_summary(task_input, execution_bundle.selected_strategy)
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
        return ContextWeaverTaskResult(
            task_id=task_input.task_id,
            agent_role=self.config.role,
            status=status,
            confidence=_CLARIFY_CONFIDENCE if requires_review else _PLANNED_CONFIDENCE,
            requires_review=requires_review,
            output=output,
        )


def _build_context_summary(
    task_input: ContextWeaverInput,
    selected_strategy: ExecutionStrategy,
) -> str:
    """Собирает компактный summary context bundle."""
    capabilities = ", ".join(task_input.candidate_capabilities) if task_input.candidate_capabilities else "none"
    return (
        f"task_kind={task_input.task_kind}; route={task_input.route}; "
        f"capabilities={capabilities}; strategy={selected_strategy}"
    )

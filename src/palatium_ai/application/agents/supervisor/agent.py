# src/palatium_ai/application/agents/supervisor/agent.py

"""Supervisor — BaseAgent implementation (030, deterministic routing)."""

from __future__ import annotations

from typing import TYPE_CHECKING, Literal, cast

from palatium_ai.application.agents.supervisor.routing import (
    FALLBACK_PLAN,
    ROUTE_MATRIX,
    clamp_confidence,
    default_plans,
)
from palatium_ai.core.logging import get_logger
from palatium_ai.core.observability.metrics import agent_metrics
from palatium_ai.core.observability.tracing import traceable
from palatium_ai.domain.agents.base import BaseAgent
from palatium_ai.domain.agents.intent import TaskKind
from palatium_ai.domain.agents.messages import AgentInput, AgentOutput
from palatium_ai.domain.agents.supervisor import SupervisorOutput
from palatium_ai.domain.agents.workflow_policy import WorkflowExecutionPolicy

if TYPE_CHECKING:
    from palatium_ai.domain.agents.agent_config import AgentConfig

logger = get_logger(__name__)


class SupervisorAgent(BaseAgent):
    """Определяет следующий маршрут по platform task kind (без LLM)."""

    @property
    def config(self) -> AgentConfig:
        return self._config

    def get_required_context_keys(self) -> list[str]:
        return ["task_kind", "requires_mcp", "classification_confidence"]

    def get_available_tools(self) -> list[str]:
        return []

    @traceable(name="supervisor.run")
    async def run(self, input: AgentInput) -> AgentOutput:
        agent_metrics.record_node_execution(self._config.role, "run")

        task_kind = cast("TaskKind", input.context["task_kind"])
        requires_mcp = input.context.get("requires_mcp", "false").lower() == "true"
        try:
            confidence = clamp_confidence(
                float(input.context["classification_confidence"]),
                default=0.0,
            )
        except TypeError, ValueError:
            confidence = 0.0

        executable_kind = WorkflowExecutionPolicy.executable_task_kind(
            task_kind,
            requires_mcp=requires_mcp,
        )

        try:
            plan = WorkflowExecutionPolicy.plan_for(
                task_kind,
                requires_mcp=requires_mcp,
                default_plans=default_plans(),
            )
        except Exception:
            logger.exception("plan_for failed", task_kind=task_kind, task_id=str(input.task_id))
            agent_metrics.record_error(self._config.role, "plan_missing")
            plan = FALLBACK_PLAN

        route, target_agent = ROUTE_MATRIX.get(executable_kind, ("researcher", "researcher"))

        requires_review = confidence < self._config.confidence_threshold
        status: Literal["success", "failure", "partial"] = "partial" if requires_review else "success"

        if requires_review:
            agent_metrics.record_human_escalation("low_confidence_route")
        if route == "clarification":
            agent_metrics.record_human_escalation("clarification_route")

        output = SupervisorOutput(
            route=route,
            target_agent=target_agent,
            confidence=confidence,
            plan=plan,
        )

        return AgentOutput(
            task_id=input.task_id,
            status=status,
            confidence=confidence,
            output=output,
            error_message=None,
        )

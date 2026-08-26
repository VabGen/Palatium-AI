# src/palatium_ai/application/agents/supervisor_agent.py

"""Агент Supervisor — роутинг/план по task kind и capabilities."""

from __future__ import annotations

from typing import TYPE_CHECKING, Literal

from palatium_ai.core.observability.metrics import agent_metrics
from palatium_ai.core.observability.tracing import traceable
from palatium_ai.domain.agents.agent_config import AgentConfig
from palatium_ai.domain.agents.intent import TaskKind
from palatium_ai.domain.agents.supervisor import (
    SupervisorInput,
    SupervisorOutput,
    SupervisorTaskResult,
    WorkerRoute,
)
from palatium_ai.domain.agents.workflow_policy import WorkflowExecutionPolicy

if TYPE_CHECKING:
    from palatium_ai.domain.agents.contracts import AgentContext


SUPERVISOR_CONFIG = AgentConfig(
    name="supervisor",
    role="supervisor",
    model_tier="mid",
    temperature=0.2,
    allowed_tools=(),
    timeout_seconds=60,
    max_retries=2,
    confidence_threshold=0.7,
)

_DEFAULT_PLANS: dict[TaskKind, str] = {
    "capability_discovery": "Определить доступные MCP-сервера и capability map перед ответом.",
    "knowledge_request": "Собрать контекст, при необходимости вызвать retrieve/search и подготовить черновой ответ.",
    "multi_step_workflow": "Зарезервировано: декомпозиция N шагов ещё не исполняется графом.",
    "tool_execution": "Подобрать нужный MCP/tool и выполнить контролируемый вызов по allow-list.",
    "response_formatting": "Преобразовать уже готовые данные в пользовательский ответ.",
    "social_conversation": "Кратко ответить на phatic/social реплику без tools и retrieval.",
    "clarification_needed": "Сформировать уточняющий вопрос до дальнейшего исполнения.",
}


class SupervisorAgent:
    """Определяет следующий маршрут по platform task kind."""

    config = SUPERVISOR_CONFIG

    @traceable(name="supervisor.execute")
    async def execute(
        self,
        task_input: SupervisorInput,
        context: AgentContext,
    ) -> SupervisorTaskResult:
        """Создаёт план маршрутизации и применяет confidence gate."""
        _ = context
        agent_metrics.record_node_execution("supervisor", "supervisor_node")

        executable_kind = WorkflowExecutionPolicy.executable_task_kind(
            task_input.task_kind,
            requires_mcp=task_input.requires_mcp,
        )
        plan = WorkflowExecutionPolicy.plan_for(
            task_input.task_kind,
            requires_mcp=task_input.requires_mcp,
            default_plans=_DEFAULT_PLANS,
        )

        if executable_kind == "social_conversation" and not task_input.requires_mcp:
            route: WorkerRoute = "formatter"
            target_agent = "formatter"
        elif executable_kind == "response_formatting":
            route = "formatter"
            target_agent = "formatter"
        elif executable_kind == "clarification_needed":
            route = "clarification"
            target_agent = "formatter"
        else:
            route = "researcher"
            target_agent = "researcher"

        requires_review = task_input.classification_confidence < self.config.confidence_threshold
        status: Literal["success", "failure", "partial"] = "partial" if requires_review else "success"

        if requires_review:
            agent_metrics.record_human_escalation("low_confidence_route")

        output = SupervisorOutput(
            route=route,
            target_agent=target_agent,
            confidence=task_input.classification_confidence,
            plan=plan,
        )

        return SupervisorTaskResult(
            task_id=task_input.task_id,
            agent_role=self.config.role,
            status=status,
            confidence=task_input.classification_confidence,
            requires_review=requires_review,
            output=output,
        )

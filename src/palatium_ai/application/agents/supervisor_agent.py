# src/palatium_ai/application/agents/supervisor_agent.py

"""Агент Supervisor — роутинг/план по task kind и capabilities."""

from __future__ import annotations

import logging
import math

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

logger = logging.getLogger(__name__)

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

_FALLBACK_PLAN = "Исполнить запрос по общему сценарию researcher → formatter."

_ROUTE_MATRIX: dict[str, tuple[WorkerRoute, str]] = {
    "social_conversation": ("formatter", "formatter"),
    "response_formatting": ("formatter", "formatter"),
    "clarification_needed": ("clarification", "formatter"),
    "multi_step_workflow": ("researcher", "researcher"),
}


class SupervisorAgent:
    """Определяет следующий маршрут по platform task kind.

    Без LLM: детерминированный роутер над результатом классификации.
    Контракт отказного пути — как у остальных агентов: исключения
    (например, KeyError на новом TaskKind) конвертируются в fallback-план
    или failure-result, а не роняют граф-ноду.
    """

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

        confidence = _clamp_confidence(task_input.classification_confidence, default=0.0)

        executable_kind = WorkflowExecutionPolicy.executable_task_kind(
            task_input.task_kind,
            requires_mcp=task_input.requires_mcp,
        )

        try:
            plan = WorkflowExecutionPolicy.plan_for(
                task_input.task_kind,
                requires_mcp=task_input.requires_mcp,
                default_plans=_DEFAULT_PLANS,
            )
        except Exception:
            logger.exception(
                "plan_for failed for kind=%s (task=%s)",
                task_input.task_kind,
                task_input.task_id,
            )
            agent_metrics.record_error("supervisor", "plan_missing")
            plan = _FALLBACK_PLAN

        route, target_agent = _ROUTE_MATRIX.get(executable_kind, ("researcher", "researcher"))

        requires_review = confidence < self.config.confidence_threshold
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

        return SupervisorTaskResult(
            task_id=task_input.task_id,
            agent_role=self.config.role,
            status=status,
            confidence=confidence,
            requires_review=requires_review,
            output=output,
        )


def _clamp_confidence(value: float, *, default: float) -> float:
    """Кламп [0, 1] с NaN/inf-guard для LLM-происхождения значения.

    TODO: заменить на общий хелпер (например,
    palatium_ai.domain.llm.scoring.clamp_score) — сейчас это седьмая
    локальная копия клампа по кодовой базе.
    """
    if not math.isfinite(value):
        return default
    return min(max(value, 0.0), 1.0)

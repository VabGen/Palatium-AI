# src/palatium_ai/application/agents/supervisor/routing.py

"""Deterministic route matrix and default plans for Supervisor."""

from __future__ import annotations

import math

from palatium_ai.domain.agents.intent import TaskKind
from palatium_ai.domain.agents.supervisor import WorkerRoute

_DEFAULT_PLANS: dict[TaskKind, str] = {
    "capability_discovery": "Определить доступные MCP-сервера и capability map перед ответом.",
    "knowledge_request": "Собрать контекст, при необходимости вызвать retrieve/search и подготовить черновой ответ.",
    "multi_step_workflow": "Зарезервировано: декомпозиция N шагов ещё не исполняется графом.",
    "tool_execution": "Подобрать нужный MCP/tool и выполнить контролируемый вызов по allow-list.",
    "response_formatting": "Преобразовать уже готовые данные в пользовательский ответ.",
    "social_conversation": "Кратко ответить на phatic/social реплику без tools и retrieval.",
    "clarification_needed": "Сформировать уточняющий вопрос до дальнейшего исполнения.",
}

FALLBACK_PLAN = "Исполнить запрос по общему сценарию researcher → formatter."

ROUTE_MATRIX: dict[str, tuple[WorkerRoute, str]] = {
    "social_conversation": ("formatter", "formatter"),
    "response_formatting": ("formatter", "formatter"),
    "clarification_needed": ("clarification", "formatter"),
    "multi_step_workflow": ("researcher", "researcher"),
}


def default_plans() -> dict[TaskKind, str]:
    return dict(_DEFAULT_PLANS)


def clamp_confidence(value: float, *, default: float) -> float:
    """Кламп [0, 1] с NaN/inf-guard."""
    if not math.isfinite(value):
        return default
    return min(max(value, 0.0), 1.0)

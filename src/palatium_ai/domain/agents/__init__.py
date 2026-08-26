# src/palatium_ai/domain/agents/__init__.py

"""Модуль agents содержит классы для работы с агентами."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from .agent_config import AgentConfig
from .agent_id import AgentId
from .context_packet import ContextPacket
from .context_weaver import ContextWeaverInput, ContextWeaverOutput, ContextWeaverTaskResult
from .contracts import AgentContext, TaskResult
from .critic import CriticInput, CriticOutput, CriticTaskResult
from .intent import IntentClassifierInput, IntentClassifierOutput, IntentTaskResult
from .researcher import ResearcherInput, ResearcherOutput, ResearcherTaskResult
from .supervisor import SupervisorInput, SupervisorOutput, SupervisorTaskResult

# Formatter импортируется лениво (избегает лишней загрузки HITL при импорте пакета agents).

if TYPE_CHECKING:
    from .formatter import FormatterInput, FormatterOutput, FormatterTaskResult

__all__ = [
    "AgentConfig",
    "AgentId",
    "AgentContext",
    "TaskResult",
    "ContextPacket",
    "ContextWeaverInput",
    "ContextWeaverOutput",
    "ContextWeaverTaskResult",
    "CriticInput",
    "CriticOutput",
    "CriticTaskResult",
    "FormatterInput",
    "FormatterOutput",
    "FormatterTaskResult",
    "IntentClassifierInput",
    "IntentClassifierOutput",
    "IntentTaskResult",
    "ResearcherInput",
    "ResearcherOutput",
    "ResearcherTaskResult",
    "SupervisorInput",
    "SupervisorOutput",
    "SupervisorTaskResult",
]

_LAZY_FORMATTER = frozenset({"FormatterInput", "FormatterOutput", "FormatterTaskResult"})


def __getattr__(name: str) -> Any:
    if name in _LAZY_FORMATTER:
        from .formatter import FormatterInput, FormatterOutput, FormatterTaskResult

        mapping = {
            "FormatterInput": FormatterInput,
            "FormatterOutput": FormatterOutput,
            "FormatterTaskResult": FormatterTaskResult,
        }
        value = mapping[name]
        globals()[name] = value
        return value
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")

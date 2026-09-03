# src/palatium_ai/domain/agents/__init__.py

"""Модуль agents содержит классы для работы с агентами.

Eager только то, что не тянет mcp.models. Иначе:
mcp.models → policies → continuity → agents.intent → этот __init__ → context_weaver → mcp.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from .agent_config import AgentConfig
from .agent_id import AgentId
from .base import BaseAgent
from .contracts import AgentContext, TaskResult
from .intent import IntentClassifierInput, IntentClassifierOutput, IntentTaskResult
from .messages import AgentInput, AgentOutput
from .supervisor import SupervisorInput, SupervisorOutput, SupervisorTaskResult

if TYPE_CHECKING:
    from .context_packet import ContextPacket
    from .context_weaver import ContextWeaverInput, ContextWeaverOutput, ContextWeaverTaskResult
    from .critic import CriticInput, CriticOutput, CriticTaskResult
    from .formatter import FormatterInput, FormatterOutput, FormatterTaskResult
    from .researcher import ResearcherInput, ResearcherOutput, ResearcherTaskResult

__all__ = [
    "AgentConfig",
    "AgentId",
    "AgentContext",
    "AgentInput",
    "AgentOutput",
    "BaseAgent",
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

_LAZY: dict[str, tuple[str, str]] = {
    "ContextPacket": (".context_packet", "ContextPacket"),
    "ContextWeaverInput": (".context_weaver", "ContextWeaverInput"),
    "ContextWeaverOutput": (".context_weaver", "ContextWeaverOutput"),
    "ContextWeaverTaskResult": (".context_weaver", "ContextWeaverTaskResult"),
    "CriticInput": (".critic", "CriticInput"),
    "CriticOutput": (".critic", "CriticOutput"),
    "CriticTaskResult": (".critic", "CriticTaskResult"),
    "FormatterInput": (".formatter", "FormatterInput"),
    "FormatterOutput": (".formatter", "FormatterOutput"),
    "FormatterTaskResult": (".formatter", "FormatterTaskResult"),
    "ResearcherInput": (".researcher", "ResearcherInput"),
    "ResearcherOutput": (".researcher", "ResearcherOutput"),
    "ResearcherTaskResult": (".researcher", "ResearcherTaskResult"),
}


def __getattr__(name: str) -> Any:
    spec = _LAZY.get(name)
    if spec is None:
        raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
    module_name, attr = spec
    from importlib import import_module

    value = getattr(import_module(module_name, __name__), attr)
    globals()[name] = value
    return value

# src/palatium_ai/domain/agents/base.py

"""Контракт BaseAgent (030) — реализации в application/agents/<name>/."""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import TYPE_CHECKING

from palatium_ai.domain.agents.agent_config import AgentConfig
from palatium_ai.domain.agents.messages import AgentInput, AgentOutput

if TYPE_CHECKING:
    from palatium_ai.domain.ports.harness import HarnessPort


class BaseAgent(ABC):
    """Абстрактный агент; LLM/tools только через Harness."""

    def __init__(self, harness: HarnessPort, config: AgentConfig) -> None:
        self._harness = harness
        self._config = config

    @abstractmethod
    async def run(self, input: AgentInput) -> AgentOutput:
        """Выполнить задачу агента."""

    @abstractmethod
    def get_required_context_keys(self) -> list[str]:
        """JIT-ключи для ContextBuilder (065)."""

    @abstractmethod
    def get_available_tools(self) -> list[str]:
        """Имена инструментов; фильтруются RBAC в ToolRegistry (070)."""

    async def verify(self, output: AgentOutput) -> bool:
        """Семантическая самопроверка; False → partial + эскалация (030.7)."""
        return True

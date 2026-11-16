# src/palatium_ai/domain/ports/harness.py

"""Порт Harness — единая точка execute_with_guardrails (065)."""

from __future__ import annotations

from typing import TYPE_CHECKING, Protocol

if TYPE_CHECKING:
    from collections.abc import Callable

    from pydantic import BaseModel

    from palatium_ai.domain.agents.agent_config import AgentConfig
    from palatium_ai.domain.agents.base import BaseAgent
    from palatium_ai.domain.agents.messages import AgentInput, AgentOutput
    from palatium_ai.domain.llm.controls import ReasoningEffort, TextVerbosity
    from palatium_ai.domain.llm.models import ChatMessage, LLMCompletion, LLMResponseFormat


class HarnessPort(Protocol):
    """Контракт инфраструктурного слоя guardrails для агентов.

    Реализация: ``application/agents/harness.py`` (Wave 2).

    Последовательность внутри execute_with_guardrails (не дублировать в узлах):

    span → secret redact (instruction) → JIT missing keys → secret redact (context) →
    compact@80% → timed run → verify → confidence gate → metrics.

    RBAC для MCP/tools — единая точка ``ToolExecutor`` (070), не шаг harness:
    агент вызывает инструменты сам; harness не фильтрует allow-list до ``run``.

    """

    async def execute_with_guardrails(
        self,
        agent: BaseAgent,
        input: AgentInput,
    ) -> AgentOutput:
        """Единая точка запуска агента из узла графа."""
        ...

    async def call_llm(
        self,
        config: AgentConfig,
        messages: list[ChatMessage],
        *,
        response_format: LLMResponseFormat | None = None,
        response_model: type[BaseModel] | None = None,
        max_tokens: int | None = None,
        reasoning_effort: ReasoningEffort | None = None,
        verbosity: TextVerbosity | None = None,
    ) -> LLMCompletion:
        """LLM call with retry, timeout, metrics (agents must not hold LLMPort directly)."""
        ...

    async def call_llm_stream(
        self,
        config: AgentConfig,
        messages: list[ChatMessage],
        *,
        response_format: LLMResponseFormat | None = None,
        response_model: type[BaseModel] | None = None,
        on_delta: Callable[[str], object] | None = None,
        max_tokens: int | None = None,
        reasoning_effort: ReasoningEffort | None = None,
        verbosity: TextVerbosity | None = None,
    ) -> LLMCompletion:
        """Streaming LLM; accumulates content and optionally forwards deltas."""
        ...

# src/palatium_ai/application/agents/base.py

"""Базовый класс агентов платформы."""

from __future__ import annotations

import asyncio

from abc import ABC, abstractmethod
from typing import TYPE_CHECKING, ClassVar

from palatium_ai.application.services.cost_budget import CostBudgetExceededError
from palatium_ai.core.exceptions import AgentExecutionError
from palatium_ai.core.logging import get_logger
from palatium_ai.core.observability.metrics import agent_metrics
from palatium_ai.core.observability.tracing import traceable
from palatium_ai.core.observability.turn_tokens import get_turn_token_collector
from palatium_ai.domain.agents.contracts import AgentContext, TaskResult
from palatium_ai.domain.llm.models import ChatMessage, LLMCompletion, LLMResponseFormat
from palatium_ai.infrastructure.llm.cost import estimate_completion_cost_usd

if TYPE_CHECKING:
    from pydantic import BaseModel

    from palatium_ai.application.services.cost_budget import CostBudgetService
    from palatium_ai.domain.agents.agent_config import AgentConfig
    from palatium_ai.domain.ports.llm import LLMPort

logger = get_logger(__name__)


class BaseAgent(ABC):
    """Абстрактный агент с retry, timeout и трассировкой LLM."""

    config: ClassVar[AgentConfig]

    def __init__(
        self,
        llm: LLMPort,
        *,
        cost_budget: CostBudgetService | None = None,
    ) -> None:
        self._llm = llm
        self._cost_budget = cost_budget

    @abstractmethod
    async def execute(self, task_input: BaseModel, context: AgentContext) -> TaskResult:
        """Выполняет задачу агента."""
        ...

    @traceable(name="agent.llm_call")
    async def _call_llm(
        self,
        messages: list[ChatMessage],
        *,
        model: str | None = None,
        response_format: LLMResponseFormat | None = None,
    ) -> LLMCompletion:
        """Вызывает LLM с retry и экспоненциальным backoff."""
        last_error: Exception | None = None
        resolved_model = model or self.config.llm_model

        if self._cost_budget is not None:
            try:
                self._cost_budget.assert_turn_allows_call()
            except CostBudgetExceededError:
                agent_metrics.record_error(self.config.role, "CostBudgetExceededError")
                raise

        for attempt in range(self.config.max_retries):
            logger.debug(
                "agent.llm_call",
                agent=self.config.name,
                agent_role=self.config.role,
                model=resolved_model,
                attempt=attempt + 1,
                max_retries=self.config.max_retries,
                response_format=response_format or "text",
            )
            try:
                if self._cost_budget is not None:
                    self._cost_budget.assert_turn_allows_call()
                completion = await asyncio.wait_for(
                    self._llm.generate(
                        messages,
                        model=model,
                        temperature=self.config.temperature,
                        response_format=response_format,
                    ),
                    timeout=self.config.timeout_seconds,
                )
                usage = completion.usage
                cost_usd = estimate_completion_cost_usd(
                    model=completion.model or (resolved_model or ""),
                    prompt_tokens=usage.prompt_tokens,
                    completion_tokens=usage.completion_tokens,
                )
                agent_metrics.record_token_usage(
                    agent_type=self.config.role,
                    model=completion.model,
                    prompt_tokens=usage.prompt_tokens,
                    completion_tokens=usage.completion_tokens,
                    cost_usd=cost_usd,
                )
                turn_tokens = get_turn_token_collector()
                if turn_tokens is not None:
                    turn_tokens.record(
                        agent=self.config.name,
                        model=completion.model,
                        prompt_tokens=usage.prompt_tokens,
                        completion_tokens=usage.completion_tokens,
                        cost_usd=cost_usd,
                    )
                return completion
            except CostBudgetExceededError:
                raise
            except Exception as exc:
                last_error = exc
                if attempt >= self.config.max_retries - 1:
                    break
                await asyncio.sleep(2**attempt)

        raise AgentExecutionError(
            f"LLM call failed after {self.config.max_retries} attempts: {last_error}",
        ) from last_error

# src/palatium_ai/application/agents/harness.py

"""Harness — execute_with_guardrails (065)."""

from __future__ import annotations

import asyncio

from typing import TYPE_CHECKING

from palatium_ai.application.services.context_builder import ContextBuilder
from palatium_ai.application.services.cost_budget import CostBudgetExceededError
from palatium_ai.core.exceptions import AgentExecutionError
from palatium_ai.core.logging import get_logger
from palatium_ai.core.observability.metrics import agent_metrics
from palatium_ai.core.observability.tracing import traceable
from palatium_ai.core.observability.turn_tokens import get_turn_token_collector
from palatium_ai.core.security.secret_scanner import SecretScanError, scan_text, scan_text_fields
from palatium_ai.domain.agents.base import BaseAgent
from palatium_ai.domain.agents.messages import AgentInput, AgentOutput
from palatium_ai.domain.llm.models import ChatMessage, LLMCompletion, LLMResponseFormat

if TYPE_CHECKING:
    from pydantic import BaseModel

    from palatium_ai.application.services.cost_budget import CostBudgetService
    from palatium_ai.domain.agents.agent_config import AgentConfig
    from palatium_ai.domain.ports.llm import LlmCostEstimatorPort, LLMPort
    from palatium_ai.infrastructure.llm.factory import LLMClientFactory

logger = get_logger(__name__)


class Harness:
    """Guardrails entry point for graph nodes (HarnessPort implementation)."""

    def __init__(
        self,
        *,
        context_builder: ContextBuilder | None = None,
        llm_factory: LLMClientFactory | None = None,
        llm: LLMPort | None = None,
        cost_budget: CostBudgetService | None = None,
        cost_estimator: LlmCostEstimatorPort | None = None,
    ) -> None:
        self._context_builder = context_builder or ContextBuilder()
        self._llm_factory = llm_factory
        self._llm = llm
        self._cost_budget = cost_budget
        self._cost_estimator = cost_estimator

    def _resolve_llm(self, config: AgentConfig) -> LLMPort:
        if self._llm is not None:
            return self._llm
        if self._llm_factory is not None:
            return self._llm_factory.get_client_for_agent(config)
        msg = "Harness has no LLM configured (llm or llm_factory required)"
        raise RuntimeError(msg)

    @traceable(name="harness.call_llm")
    async def call_llm(
        self,
        config: AgentConfig,
        messages: list[ChatMessage],
        *,
        response_format: LLMResponseFormat | None = None,
    ) -> LLMCompletion:
        """LLM with retry/backoff, budget guard, token metrics (030)."""
        llm = self._resolve_llm(config)
        last_error: Exception | None = None
        resolved_model = config.llm_model

        if self._cost_budget is not None:
            self._cost_budget.assert_turn_allows_call()

        for attempt in range(config.max_retries):
            logger.debug(
                "harness.llm_call",
                agent=config.name,
                agent_role=config.role,
                model=resolved_model,
                attempt=attempt + 1,
                max_retries=config.max_retries,
                response_format=response_format or "text",
            )
            try:
                if self._cost_budget is not None:
                    self._cost_budget.assert_turn_allows_call()
                completion = await asyncio.wait_for(
                    llm.generate(
                        messages,
                        model=resolved_model,
                        temperature=config.temperature,
                        response_format=response_format,
                    ),
                    timeout=config.timeout_seconds,
                )
                usage = completion.usage
                cost_usd = 0.0
                if self._cost_estimator is not None:
                    cost_usd = self._cost_estimator(
                        model=completion.model or (resolved_model or ""),
                        prompt_tokens=usage.prompt_tokens,
                        completion_tokens=usage.completion_tokens,
                    )
                agent_metrics.record_token_usage(
                    agent_type=config.role,
                    model=completion.model,
                    prompt_tokens=usage.prompt_tokens,
                    completion_tokens=usage.completion_tokens,
                    cost_usd=cost_usd,
                )
                turn_tokens = get_turn_token_collector()
                if turn_tokens is not None:
                    turn_tokens.record(
                        agent=config.name,
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
                if attempt >= config.max_retries - 1:
                    break
                await asyncio.sleep(2**attempt)

        raise AgentExecutionError(
            f"LLM call failed after {config.max_retries} attempts: {last_error}",
        ) from last_error

    @traceable(name="harness.execute_with_guardrails")
    async def execute_with_guardrails(
        self,
        agent: BaseAgent,
        input: AgentInput,
    ) -> AgentOutput:
        """Domain agent path: JIT context → secret scan → run → verify → confidence gate."""
        role = agent._config.role
        agent_metrics.record_node_execution(role, "harness_execute")

        try:
            scan_text(input.instruction, field="instruction")
            scan_text_fields(input.context)
        except SecretScanError as exc:
            agent_metrics.record_error(role, "SecretScanError")
            return AgentOutput(
                task_id=input.task_id,
                status="failure",
                confidence=0.0,
                output=_empty_output_payload(input.task_id),
                error_message=str(exc),
            )

        keys = agent.get_required_context_keys()
        missing = [key for key in keys if key not in input.context]
        if missing:
            thread_id = input.context.get("_thread_id", str(input.task_id))
            user_id = input.context.get("_user_id")
            try:
                built = await self._context_builder.build(
                    missing,
                    thread_id=thread_id,
                    user_id=user_id,
                    instruction=input.instruction,
                )
                input = input.model_copy(update={"context": {**input.context, **built}})
            except KeyError as exc:
                agent_metrics.record_error(role, "ContextBuildError")
                return AgentOutput(
                    task_id=input.task_id,
                    status="failure",
                    confidence=0.0,
                    output=_empty_output_payload(input.task_id),
                    error_message=str(exc),
                )

        try:
            output = await asyncio.wait_for(
                agent.run(input),
                timeout=agent._config.timeout_seconds,
            )
        except TimeoutError:
            agent_metrics.record_error(role, "TimeoutError")
            return AgentOutput(
                task_id=input.task_id,
                status="failure",
                confidence=0.0,
                output=_empty_output_payload(input.task_id),
                error_message=f"Agent timed out after {agent._config.timeout_seconds}s",
            )
        except Exception as exc:
            agent_metrics.record_error(role, type(exc).__name__)
            logger.exception("harness.run_failed", agent=role, task_id=str(input.task_id))
            return AgentOutput(
                task_id=input.task_id,
                status="failure",
                confidence=0.0,
                output=_empty_output_payload(input.task_id),
                error_message=str(exc),
            )

        if not await agent.verify(output) and output.status == "success":
            output = output.model_copy(update={"status": "partial"})

        if output.confidence < agent._config.confidence_threshold and output.status == "success":
            output = output.model_copy(update={"status": "partial"})
            agent_metrics.record_human_escalation(f"low_confidence_{role}")

        return output


def _empty_output_payload(task_id: object) -> BaseModel:
    from pydantic import BaseModel, Field

    class _HarnessFailureOutput(BaseModel):
        model_config = {"frozen": True}

        task_id: str = Field(default_factory=lambda: str(task_id))

    return _HarnessFailureOutput()

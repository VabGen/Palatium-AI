# src/palatium_ai/application/agents/harness.py

"""Harness — execute_with_guardrails (065)."""

from __future__ import annotations

import asyncio
import inspect

from collections.abc import AsyncIterator, Callable
from typing import TYPE_CHECKING

from palatium_ai.application.services.context_builder import ContextBuilder
from palatium_ai.application.services.cost_budget import CostBudgetExceededError
from palatium_ai.core.exceptions import AgentExecutionError
from palatium_ai.core.logging import get_logger
from palatium_ai.core.observability.metrics import agent_metrics
from palatium_ai.core.observability.tracing import traceable
from palatium_ai.core.observability.turn_tokens import get_turn_token_collector
from palatium_ai.core.resilience import CircuitOpenError
from palatium_ai.core.security.secret_scanner import (
    redact_text,
    secret_pattern_labels,
)
from palatium_ai.domain.agents.base import BaseAgent
from palatium_ai.domain.agents.messages import AgentInput, AgentOutput
from palatium_ai.domain.llm.errors import StructuredOutputUnsupportedError
from palatium_ai.domain.llm.models import (
    ChatMessage,
    LLMCompletion,
    LLMResponseFormat,
    LLMStreamDelta,
    LLMUsage,
)
from palatium_ai.domain.llm.structured_output import assert_json_schema_model
from palatium_ai.domain.memory.compact import CompactRequest

if TYPE_CHECKING:
    from pydantic import BaseModel

    from palatium_ai.application.services.cost_budget import CostBudgetService
    from palatium_ai.domain.agents.agent_config import AgentConfig
    from palatium_ai.domain.ports.llm import LlmCostEstimatorPort, LLMPort
    from palatium_ai.infrastructure.llm.factory import LLMClientFactory

DeltaCallback = Callable[[str], object]

logger = get_logger(__name__)


def _with_system_prompt_cache(messages: list[ChatMessage]) -> list[ChatMessage]:
    """Mark the leading system message for provider prompt/prefix cache (P0.3)."""
    if not messages:
        return messages
    first = messages[0]
    if first.role != "system" or first.cache_control is not None:
        return messages
    return [first.model_copy(update={"cache_control": "ephemeral"}), *messages[1:]]


async def _accumulate_stream_deltas(
    deltas: AsyncIterator[LLMStreamDelta],
    *,
    on_delta: DeltaCallback | None,
    initial_model: str,
) -> LLMCompletion:
    """Join stream chunks into one completion; optionally forward content deltas."""
    pieces: list[str] = []
    finish_reason: str | None = None
    usage = LLMUsage()
    cost_usd: float | None = None
    model = initial_model
    async for delta in deltas:
        if delta.content:
            pieces.append(delta.content)
            if on_delta is not None:
                maybe = on_delta(delta.content)
                if inspect.isawaitable(maybe):
                    await maybe
        if delta.finish_reason:
            finish_reason = delta.finish_reason
        if delta.usage is not None:
            usage = delta.usage
        if delta.cost_usd is not None:
            cost_usd = delta.cost_usd
        if delta.model:
            model = delta.model
    return LLMCompletion(
        content="".join(pieces),
        model=model,
        usage=usage,
        finish_reason=finish_reason,
        cost_usd=cost_usd,
    )


def _resolve_cost_usd(
    *,
    completion: LLMCompletion,
    fallback_model: str,
    estimator: LlmCostEstimatorPort | None,
) -> float:
    """Prefer the provider/gateway-reported cost; fall back to the local price table (040).

    A gateway resolving opaque tier aliases (``tier-small`` → real model) is the only
    component that can price the call, so its reported cost is authoritative. The local
    estimator cannot resolve an alias at all and raised on every call, which left
    ``palatium_agent_cost_usd_total`` permanently at zero.
    """
    if completion.cost_usd is not None:
        return completion.cost_usd
    if estimator is None:
        return 0.0
    return estimator(
        model=completion.model or fallback_model,
        prompt_tokens=completion.usage.prompt_tokens,
        completion_tokens=completion.usage.completion_tokens,
    )


def _missing_cost_reason(*, model: str) -> str:
    """Closed reason set for ``palatium_llm_cost_missing_total`` (040 cardinality)."""
    if model.strip().lower().startswith("tier-"):
        return "tier_alias"
    return "unpriced_model"


def _record_missing_cost_if_needed(
    *,
    completion: LLMCompletion,
    cost_usd: float,
    fallback_model: str,
    agent_role: str,
) -> None:
    """Emit metric+log when tokens exist but USD is unresolved (gateway gap)."""
    usage = completion.usage
    if completion.cost_usd is not None:
        return
    if cost_usd > 0.0:
        return
    if usage.prompt_tokens <= 0 and usage.completion_tokens <= 0:
        return
    model = (completion.model or fallback_model or "unknown").strip() or "unknown"
    reason = _missing_cost_reason(model=model)
    agent_metrics.record_llm_cost_missing(reason=reason)
    logger.debug(
        "llm.cost.missing",
        agent_role=agent_role,
        model=model,
        reason=reason,
        prompt_tokens=usage.prompt_tokens,
        completion_tokens=usage.completion_tokens,
    )


def _redact_secret_fields(value: str, *, agent_type: str, stage: str) -> str:
    """Mask secret-shaped substrings, recording a metric when anything matched (020, 040)."""
    labels = secret_pattern_labels(value)
    if not labels:
        return value
    agent_metrics.record_secret_redaction(agent_type=agent_type, stage=stage)
    logger.warning(
        "harness.secret_redacted",
        agent=agent_type,
        stage=stage,
        rules=list(labels),
    )
    return redact_text(value)


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

    def _record_llm_usage(
        self,
        *,
        config: AgentConfig,
        completion: LLMCompletion,
        fallback_model: str,
    ) -> None:
        usage = completion.usage
        cost_usd = _resolve_cost_usd(
            completion=completion,
            fallback_model=fallback_model,
            estimator=self._cost_estimator,
        )
        _record_missing_cost_if_needed(
            completion=completion,
            cost_usd=cost_usd,
            fallback_model=fallback_model,
            agent_role=config.role,
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

    @traceable(name="harness.call_llm")
    async def call_llm(
        self,
        config: AgentConfig,
        messages: list[ChatMessage],
        *,
        response_format: LLMResponseFormat | None = None,
        response_model: type[BaseModel] | None = None,
        max_tokens: int | None = None,
    ) -> LLMCompletion:
        """LLM with retry/backoff, budget guard, token metrics (030)."""
        assert_json_schema_model(response_format, response_model)
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
                cached_messages = _with_system_prompt_cache(messages)
                completion = await asyncio.wait_for(
                    llm.generate(
                        cached_messages,
                        model=resolved_model,
                        temperature=config.temperature,
                        max_tokens=max_tokens,
                        response_format=response_format,
                        response_model=response_model,
                    ),
                    timeout=config.timeout_seconds,
                )
                self._record_llm_usage(
                    config=config,
                    completion=completion,
                    fallback_model=resolved_model or "",
                )
                return completion
            except CostBudgetExceededError:
                raise
            except StructuredOutputUnsupportedError:
                raise
            except CircuitOpenError as exc:
                # All provider breakers are open: every retry would just re-check the
                # breaker and sleep, so fail immediately with the platform error type.
                raise AgentExecutionError(f"LLM provider circuit open: {exc}") from exc
            except Exception as exc:
                last_error = exc
                if attempt >= config.max_retries - 1:
                    break
                await asyncio.sleep(2**attempt)

        raise AgentExecutionError(
            f"LLM call failed after {config.max_retries} attempts: {last_error}",
        ) from last_error

    @traceable(name="harness.call_llm_stream")
    async def call_llm_stream(
        self,
        config: AgentConfig,
        messages: list[ChatMessage],
        *,
        response_format: LLMResponseFormat | None = None,
        response_model: type[BaseModel] | None = None,
        on_delta: DeltaCallback | None = None,
        max_tokens: int | None = None,
    ) -> LLMCompletion:
        """Streaming LLM; accumulates content and optionally forwards deltas (W1.4)."""
        assert_json_schema_model(response_format, response_model)
        llm = self._resolve_llm(config)
        resolved_model = config.llm_model
        if self._cost_budget is not None:
            self._cost_budget.assert_turn_allows_call()

        cached_messages = _with_system_prompt_cache(messages)
        initial_model = (resolved_model or "").strip() or "unknown"
        try:
            completion = await asyncio.wait_for(
                _accumulate_stream_deltas(
                    llm.generate_stream(
                        cached_messages,
                        model=resolved_model,
                        temperature=config.temperature,
                        max_tokens=max_tokens,
                        response_format=response_format,
                        response_model=response_model,
                    ),
                    on_delta=on_delta,
                    initial_model=initial_model,
                ),
                timeout=config.timeout_seconds,
            )
        except TimeoutError as exc:
            raise AgentExecutionError(
                f"LLM stream timed out after {config.timeout_seconds}s",
            ) from exc
        except StructuredOutputUnsupportedError:
            raise
        except CircuitOpenError as exc:
            raise AgentExecutionError(f"LLM provider circuit open: {exc}") from exc

        self._record_llm_usage(
            config=config,
            completion=completion,
            fallback_model=resolved_model or "",
        )
        return completion

    @traceable(name="harness.execute_with_guardrails")
    async def execute_with_guardrails(
        self,
        agent: BaseAgent,
        input: AgentInput,
    ) -> AgentOutput:
        """Domain agent path: JIT context → secret redaction → run → verify → confidence gate."""
        role = agent._config.role
        agent_metrics.record_node_execution(role, "harness_execute")

        # The instruction crosses the LLM boundary, not a durable write path: a
        # credential-shaped token must never reach the model, but it must not brick
        # the thread either — mask it and continue (020, redact_text contract).
        instruction = _redact_secret_fields(
            input.instruction,
            agent_type=role,
            stage="instruction",
        )
        if instruction != input.instruction:
            input = input.model_copy(update={"instruction": instruction})

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

        # Context assembled here is history/derived data, so it is masked rather than
        # rejected; the second pass covers the compaction summary's own output (020).
        input = self._redact_context_secrets(input, agent_type=role, stage="assembled_context")
        input = await self._maybe_compact_context(agent, input)
        input = self._redact_context_secrets(input, agent_type=role, stage="compacted_context")

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

    def _redact_context_secrets(
        self,
        input: AgentInput,
        *,
        agent_type: str,
        stage: str,
    ) -> AgentInput:
        """Mask secret-shaped substrings in every string context value (020).

        Context is assembled history/derived data (including ``dialog_window_json``),
        so a credential that slipped into an earlier turn must not poison the whole
        thread — it is redacted here, on every read, rather than hard-failing.
        """
        redacted: dict[str, str] = {}
        changed = False
        for key, value in input.context.items():
            if isinstance(value, str):
                masked = redact_text(value)
                if masked != value:
                    agent_metrics.record_secret_redaction(
                        agent_type=agent_type,
                        stage=f"{stage}.{key}",
                    )
                    logger.warning(
                        "harness.secret_redacted",
                        agent=agent_type,
                        stage=stage,
                        context_key=key,
                        rules=list(secret_pattern_labels(value)),
                    )
                    redacted[key] = masked
                    changed = True
        if not changed:
            return input
        return input.model_copy(update={"context": {**input.context, **redacted}})

    async def _maybe_compact_context(self, agent: BaseAgent, input: AgentInput) -> AgentInput:
        """Compact dialog history at 80% tier budget; preserve goal/plan/last_results (065)."""
        history = input.context.get("history")
        if not isinstance(history, str) or not history.strip():
            return input
        thread_id = (input.context.get("_thread_id") or str(input.task_id)).strip()
        user_id = input.context.get("_user_id")
        result = await self._context_builder.compact(
            CompactRequest(
                dialog=history,
                goal=input.context.get("goal", ""),
                plan=input.context.get("plan", ""),
                last_results=input.context.get("last_results", ""),
                model_tier=agent._config.model_tier,
                thread_id=thread_id,
                user_id=user_id if isinstance(user_id, str) else None,
            )
        )
        if not result.did_compact:
            return input
        updated = {
            **input.context,
            "history": result.dialog,
            "goal": result.goal,
            "plan": result.plan,
            "last_results": result.last_results,
        }
        return input.model_copy(update={"context": updated})


def _empty_output_payload(task_id: object) -> BaseModel:
    from pydantic import BaseModel, Field

    class _HarnessFailureOutput(BaseModel):
        model_config = {"frozen": True}

        task_id: str = Field(default_factory=lambda: str(task_id))

    return _HarnessFailureOutput()

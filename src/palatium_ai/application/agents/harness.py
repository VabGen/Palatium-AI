# src/palatium_ai/application/agents/harness.py

"""Harness — execute_with_guardrails (065)."""

from __future__ import annotations

import asyncio
import inspect

from collections.abc import AsyncIterator, Callable
from typing import TYPE_CHECKING

from palatium_ai.application.services.context_builder import ContextBuilder
from palatium_ai.application.services.cost_budget import CostBudgetExceededError
from palatium_ai.core.config import get_settings
from palatium_ai.core.context.tokens import count_tokens
from palatium_ai.core.exceptions import AgentExecutionError
from palatium_ai.core.logging import get_logger
from palatium_ai.core.logging.context import user_id_var
from palatium_ai.core.observability.metrics import agent_metrics
from palatium_ai.core.observability.redaction import hash8
from palatium_ai.core.observability.tracing import add_gen_ai_attributes, traceable
from palatium_ai.core.observability.turn_tokens import get_turn_token_collector
from palatium_ai.core.resilience import CircuitOpenError
from palatium_ai.core.resilience.retry import retry_async
from palatium_ai.core.security.secret_scanner import (
    redact_text,
    secret_pattern_labels,
)
from palatium_ai.domain.agents.base import BaseAgent
from palatium_ai.domain.agents.messages import AgentInput, AgentOutput
from palatium_ai.domain.agents.output_contracts import check_agent_output_schema
from palatium_ai.domain.content.citations import CitationRef
from palatium_ai.domain.llm.controls import ReasoningEffort, TextVerbosity
from palatium_ai.domain.llm.errors import EmptyLLMCompletionError, StructuredOutputUnsupportedError
from palatium_ai.domain.llm.models import (
    ChatMessage,
    LLMCompletion,
    LLMResponseFormat,
    LLMStreamDelta,
    LLMUsage,
)
from palatium_ai.domain.llm.structured_output import assert_json_schema_model
from palatium_ai.domain.memory.compact import CompactRequest
from palatium_ai.domain.policies.llm_retry import default_llm_retry_policy, is_transient_llm_error
from palatium_ai.domain.policies.llm_timeout import compute_llm_timeout_seconds
from palatium_ai.domain.policies.prompt_assembly import PromptAssemblyPolicy
from palatium_ai.domain.policies.reasoning_effort import ReasoningEffortPolicy
from palatium_ai.domain.policies.subagent_context import (
    assert_fresh_handoff_context,
    context_char_len,
    context_ratio,
)

if TYPE_CHECKING:
    from pydantic import BaseModel

    from palatium_ai.application.services.cost_budget import CostBudgetService
    from palatium_ai.core.observability.cost_tracker import CostTracker
    from palatium_ai.domain.agents.agent_config import AgentConfig
    from palatium_ai.domain.ports.llm import LlmCostEstimatorPort, LLMPort
    from palatium_ai.infrastructure.llm.factory import LLMClientFactory

DeltaCallback = Callable[[str], object]

logger = get_logger(__name__)

_DEFAULT_MAX_TOKENS = 2048
_PROMPT_ARCHIVE_MAX_CHARS = 4_000


def _maybe_archive_prompts(*, agent_role: str, messages: list[ChatMessage]) -> None:
    """Opt-in redacted prompt archive for debug threads (dev-only setting, 020).

    When ``LLM_PROMPT_ARCHIVE_ENABLED=False`` (prod default) this returns before any
    redaction/join work and never emits ``harness.llm_prompt_archive`` — no prompt
    body reaches Sentry/OTel via this path. No archive-only heavy imports.
    """
    try:
        settings = get_settings()
    except Exception:  # noqa: BLE001  # settings may be unavailable in unit stubs
        return
    if not settings.observability.llm_prompt_archive_enabled:
        return
    if settings.app.environment != "development":
        return
    parts: list[str] = []
    for message in messages:
        redacted = redact_text(message.content or "")
        parts.append(f"{message.role}:{redacted}")
    joined = "\n".join(parts)
    logger.info(
        "harness.llm_prompt_archive",
        agent_role=agent_role,
        prompt_hash=hash8(joined),
        prompt_chars=len(joined),
        prompt_preview=joined[:_PROMPT_ARCHIVE_MAX_CHARS],
    )


def _prompt_token_estimate(messages: list[ChatMessage]) -> int:
    """JIT token estimate for dynamic timeout (065 tokenizer helper)."""
    return sum(count_tokens(message.content) for message in messages)


def _resolve_call_timeout_seconds(
    config: AgentConfig,
    messages: list[ChatMessage],
    *,
    max_tokens: int | None,
) -> float:
    """Dynamic provider timeout capped by agent budget (Phase 4) and per-call ceiling."""
    dynamic = compute_llm_timeout_seconds(
        prompt_tokens=_prompt_token_estimate(messages),
        max_tokens=max_tokens if max_tokens is not None else _DEFAULT_MAX_TOKENS,
    )
    resolved = min(dynamic, float(config.timeout_seconds))
    if config.llm_call_timeout_seconds is not None:
        # A retry loop multiplies this bound: without the ceiling, a classification
        # call could sit on the provider until the whole-agent budget expires.
        resolved = min(resolved, float(config.llm_call_timeout_seconds))
    return resolved


def _record_prompt_assembly_tiers(messages: list[ChatMessage]) -> None:
    """Count which PromptAssembly system tiers actually hit the provider (CMD2)."""
    recorded = False
    for message in messages:
        if message.role != "system":
            continue
        content = (message.content or "").lstrip()
        if content.startswith("## Stable"):
            agent_metrics.record_prompt_cache_hint(tier="stable")
            recorded = True
        elif content.startswith("## Context"):
            agent_metrics.record_prompt_cache_hint(tier="context")
            recorded = True
        elif content.startswith("## Volatile"):
            agent_metrics.record_prompt_cache_hint(tier="volatile")
            recorded = True
    if not recorded and messages and messages[0].role == "system" and messages[0].cache_control == "ephemeral":
        # Legacy single system prompt (no assemble headers) still counts as stable.
        agent_metrics.record_prompt_cache_hint(tier="stable")


def _with_system_prompt_cache(messages: list[ChatMessage]) -> list[ChatMessage]:
    """Mark the leading stable system message for provider prompt/prefix cache (CMD2)."""
    cached = PromptAssemblyPolicy.apply_cache_hints(messages)
    _record_prompt_assembly_tiers(cached)
    return cached


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
    citations: list[CitationRef] = []
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
        if delta.citations:
            citations.extend(delta.citations)
    return LLMCompletion(
        content="".join(pieces),
        model=model,
        usage=usage,
        finish_reason=finish_reason,
        cost_usd=cost_usd,
        citations=tuple(citations),
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
        cost_tracker: CostTracker | None = None,
    ) -> None:
        self._context_builder = context_builder or ContextBuilder()
        self._llm_factory = llm_factory
        self._llm = llm
        self._cost_budget = cost_budget
        self._cost_estimator = cost_estimator
        self._cost_tracker = cost_tracker

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
    ) -> float:
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
        agent_metrics.record_prompt_cache_tokens(
            cache_read_tokens=usage.cache_read_tokens,
            cache_write_tokens=usage.cache_write_tokens,
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
        self._stamp_gen_ai_span(
            completion=completion,
            fallback_model=fallback_model,
            cost_usd=cost_usd,
        )
        return cost_usd

    def _stamp_gen_ai_span(
        self,
        *,
        completion: LLMCompletion,
        fallback_model: str,
        cost_usd: float,
    ) -> None:
        try:
            from opentelemetry import trace
        except ImportError:  # pragma: no cover
            return
        span = trace.get_current_span()
        if span is None or not span.is_recording():
            return
        model = (completion.model or fallback_model or "unknown").strip() or "unknown"
        add_gen_ai_attributes(
            span,
            model=model,
            usage=completion.usage,
            cost_usd=cost_usd,
            finish_reason=completion.finish_reason,
        )

    async def _track_cost_if_needed(
        self,
        *,
        config: AgentConfig,
        completion: LLMCompletion,
        cost_usd: float,
    ) -> None:
        if self._cost_tracker is None or cost_usd <= 0.0:
            return
        await self._cost_tracker.record(
            org_id="default",
            user_id=user_id_var.get() or "anonymous",
            agent_role=config.role,
            model=completion.model or "unknown",
            cost_usd=cost_usd,
        )

    async def _llm_generate_once(
        self,
        *,
        llm: LLMPort,
        config: AgentConfig,
        messages: list[ChatMessage],
        resolved_model: str | None,
        response_format: LLMResponseFormat | None,
        response_model: type[BaseModel] | None,
        max_tokens: int | None,
        attempt: int,
        prompt_version: str,
        reasoning_effort: ReasoningEffort | None,
        verbosity: TextVerbosity | None,
    ) -> LLMCompletion:
        """One LLM attempt — empty completion raises into the retry loop (W8.3)."""
        logger.debug(
            "harness.llm_call",
            agent=config.name,
            agent_role=config.role,
            model=resolved_model,
            attempt=attempt,
            max_retries=config.max_retries,
            response_format=response_format or "text",
            prompt_version=prompt_version,
            reasoning_effort=reasoning_effort,
            verbosity=verbosity,
        )
        if self._cost_budget is not None:
            self._cost_budget.assert_turn_allows_call()
        cached_messages = _with_system_prompt_cache(messages)
        _maybe_archive_prompts(agent_role=config.role, messages=cached_messages)
        call_timeout = _resolve_call_timeout_seconds(config, cached_messages, max_tokens=max_tokens)
        completion = await asyncio.wait_for(
            llm.generate(
                cached_messages,
                model=resolved_model,
                temperature=config.temperature,
                max_tokens=max_tokens,
                response_format=response_format,
                response_model=response_model,
                timeout_seconds=call_timeout,
                reasoning_effort=reasoning_effort,
                verbosity=verbosity,
            ),
            timeout=call_timeout,
        )
        if not completion.content.strip() and not completion.citations:
            agent_metrics.record_error(config.role, "llm_empty_response")
            logger.warning(
                "llm.empty_response",
                agent=config.name,
                agent_role=config.role,
                model=resolved_model,
                attempt=attempt,
                max_retries=config.max_retries,
                response_format=response_format or "text",
                finish_reason=completion.finish_reason,
                prompt_version=prompt_version,
            )
            raise EmptyLLMCompletionError(
                model=completion.model or resolved_model or "",
                finish_reason=completion.finish_reason,
            )
        cost_usd = self._record_llm_usage(
            config=config,
            completion=completion,
            fallback_model=resolved_model or "",
        )
        await self._track_cost_if_needed(config=config, completion=completion, cost_usd=cost_usd)
        return completion

    @traceable(name="harness.call_llm")
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
        """LLM with shared RetryPolicy backoff, budget guard, token metrics (030, W8.3)."""
        assert_json_schema_model(response_format, response_model)
        llm = self._resolve_llm(config)
        resolved_model = config.llm_model
        prompt_version = _prompt_version_for_role(config.role)
        effort, verb = _resolve_llm_controls(
            config,
            reasoning_effort=reasoning_effort,
            verbosity=verbosity,
        )
        policy = default_llm_retry_policy(max_attempts=config.max_retries)
        attempt_box = {"n": 0}

        if self._cost_budget is not None:
            self._cost_budget.assert_turn_allows_call()

        async def _once() -> LLMCompletion:
            attempt_box["n"] += 1
            return await self._llm_generate_once(
                llm=llm,
                config=config,
                messages=messages,
                resolved_model=resolved_model,
                response_format=response_format,
                response_model=response_model,
                max_tokens=max_tokens,
                attempt=attempt_box["n"],
                prompt_version=prompt_version,
                reasoning_effort=effort,
                verbosity=verb,
            )

        def _on_retry(state: object) -> None:
            agent_metrics.record_error(config.role, "llm_attempt_failed")
            outcome = getattr(state, "outcome", None)
            error = outcome.exception() if outcome is not None and hasattr(outcome, "exception") else None
            logger.warning(
                "llm.attempt_failed",
                agent=config.name,
                agent_role=config.role,
                model=resolved_model,
                attempt=getattr(state, "attempt_number", attempt_box["n"]),
                max_retries=config.max_retries,
                error_type=type(error).__name__ if error is not None else None,
                retrying=True,
                prompt_version=prompt_version,
            )

        try:
            return await retry_async(
                _once,
                policy=policy,
                is_retryable=_is_retryable_llm_call,
                description=f"llm.{config.role}",
                on_retry=_on_retry,
            )
        except CostBudgetExceededError, StructuredOutputUnsupportedError:
            raise
        except CircuitOpenError as exc:
            raise AgentExecutionError(f"LLM provider circuit open: {exc}") from exc
        except Exception as exc:
            if not isinstance(exc, AgentExecutionError):
                agent_metrics.record_error(config.role, "llm_attempt_failed")
            raise AgentExecutionError(
                f"LLM call failed after {config.max_retries} attempts: {exc}",
            ) from exc

    async def _stream_once(
        self,
        *,
        llm: LLMPort,
        config: AgentConfig,
        cached_messages: list[ChatMessage],
        resolved_model: str | None,
        response_format: LLMResponseFormat | None,
        response_model: type[BaseModel] | None,
        on_delta: DeltaCallback | None,
        max_tokens: int | None,
        call_timeout: float,
        initial_model: str,
        reasoning_effort: ReasoningEffort | None,
        verbosity: TextVerbosity | None,
    ) -> tuple[LLMCompletion, bool]:
        """One stream attempt; returns (completion, forwarded_any_delta)."""
        forwarded = False

        def _guarded_on_delta(chunk: str, *, _cb: DeltaCallback | None = on_delta) -> object:
            nonlocal forwarded
            if chunk:
                forwarded = True
            if _cb is None:
                return None
            return _cb(chunk)

        if self._cost_budget is not None:
            self._cost_budget.assert_turn_allows_call()
        completion = await asyncio.wait_for(
            _accumulate_stream_deltas(
                llm.generate_stream(
                    cached_messages,
                    model=resolved_model,
                    temperature=config.temperature,
                    max_tokens=max_tokens,
                    response_format=response_format,
                    response_model=response_model,
                    timeout_seconds=call_timeout,
                    reasoning_effort=reasoning_effort,
                    verbosity=verbosity,
                ),
                on_delta=_guarded_on_delta,
                initial_model=initial_model,
            ),
            timeout=call_timeout,
        )
        if not completion.content.strip() and not completion.citations:
            agent_metrics.record_error(config.role, "llm_empty_response")
            raise EmptyLLMCompletionError(
                model=completion.model or resolved_model or "",
                finish_reason=completion.finish_reason,
            )
        cost_usd = self._record_llm_usage(
            config=config,
            completion=completion,
            fallback_model=resolved_model or "",
        )
        await self._track_cost_if_needed(
            config=config,
            completion=completion,
            cost_usd=cost_usd,
        )
        return completion, forwarded

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
        reasoning_effort: ReasoningEffort | None = None,
        verbosity: TextVerbosity | None = None,
    ) -> LLMCompletion:
        """Streaming LLM with retries only before the first delta (no UI duplicates)."""
        assert_json_schema_model(response_format, response_model)
        llm = self._resolve_llm(config)
        resolved_model = config.llm_model
        effort, verb = _resolve_llm_controls(
            config,
            reasoning_effort=reasoning_effort,
            verbosity=verbosity,
        )
        if self._cost_budget is not None:
            self._cost_budget.assert_turn_allows_call()

        cached_messages = _with_system_prompt_cache(messages)
        _maybe_archive_prompts(agent_role=config.role, messages=cached_messages)
        call_timeout = _resolve_call_timeout_seconds(config, cached_messages, max_tokens=max_tokens)
        initial_model = (resolved_model or "").strip() or "unknown"
        last_error: Exception | None = None

        for attempt in range(config.max_retries):
            forwarded = False
            try:
                completion, forwarded = await self._stream_once(
                    llm=llm,
                    config=config,
                    cached_messages=cached_messages,
                    resolved_model=resolved_model,
                    response_format=response_format,
                    response_model=response_model,
                    on_delta=on_delta,
                    max_tokens=max_tokens,
                    call_timeout=call_timeout,
                    reasoning_effort=effort,
                    verbosity=verb,
                    initial_model=initial_model,
                )
                return completion
            except CostBudgetExceededError:
                raise
            except StructuredOutputUnsupportedError:
                raise
            except CircuitOpenError as exc:
                raise AgentExecutionError(f"LLM provider circuit open: {exc}") from exc
            except TimeoutError as exc:
                last_error = AgentExecutionError(f"LLM stream timed out after {call_timeout:g}s")
                last_error.__cause__ = exc
            except Exception as exc:  # noqa: BLE001  # stream retry captures provider failure (030)
                last_error = exc

            retrying = attempt < config.max_retries - 1 and not forwarded
            agent_metrics.record_error(config.role, "llm_stream_attempt_failed")
            logger.warning(
                "llm.stream_attempt_failed",
                agent=config.name,
                agent_role=config.role,
                model=resolved_model,
                attempt=attempt + 1,
                max_retries=config.max_retries,
                error_type=type(last_error).__name__ if last_error else "unknown",
                retrying=retrying,
                forwarded=forwarded,
            )
            if not retrying:
                break
            await asyncio.sleep(2**attempt)

        if isinstance(last_error, AgentExecutionError):
            raise last_error
        raise AgentExecutionError(
            f"LLM stream failed after {config.max_retries} attempts: {last_error}",
        ) from last_error

    def _reject_dirty_handoff(self, *, role: str, input: AgentInput) -> AgentOutput | None:
        """W7.1 isolation gate — fail-closed on pollution / keys outside allow-list."""
        parent_role = (input.context.get("_parent_role") or "").strip()
        if not parent_role:
            return None
        dirty = assert_fresh_handoff_context(input.context)
        if dirty:
            agent_metrics.record_error(role, "DirtyParentContext")
            return AgentOutput(
                task_id=input.task_id,
                status="failure",
                confidence=0.0,
                output=_empty_output_payload(input.task_id),
                error_message=f"forbidden parent dump keys: {dirty}",
            )
        parent_chars = int(input.context.get("_parent_context_chars") or "0")
        child_chars = context_char_len(input.context) + len(input.instruction)
        agent_metrics.record_subagent_context_ratio(
            parent_role=parent_role,
            child_role=role,
            ratio=context_ratio(child_chars=child_chars, parent_chars=parent_chars),
        )
        return None

    async def _prepare_agent_input(self, agent: BaseAgent, input: AgentInput, *, role: str) -> AgentInput | AgentOutput:
        """Redact + JIT context + compact; returns AgentOutput on context-build failure."""
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

        input = self._redact_context_secrets(input, agent_type=role, stage="assembled_context")
        input = await self._maybe_compact_context(agent, input)
        return self._redact_context_secrets(input, agent_type=role, stage="compacted_context")

    async def _verify_after_run(
        self,
        agent: BaseAgent,
        output: AgentOutput,
        *,
        role: str,
    ) -> tuple[AgentOutput, str]:
        """Schema gate then agent.verify (W8.4 before LLM-judge)."""
        mismatch = check_agent_output_schema(
            role=role,
            payload=output.output,
            status=output.status,
        )
        if mismatch is not None:
            output = output.model_copy(
                update={
                    "status": "failure",
                    "error_message": f"schema_mismatch:{mismatch}",
                    "confidence": 0.0,
                }
            )
            agent_metrics.record_human_escalation(f"verify_failed_{role}")
            return output, f"schema_mismatch:{mismatch}"

        if not await agent.verify(output) and output.status == "success":
            output = output.model_copy(update={"status": "partial"})
            agent_metrics.record_human_escalation(f"verify_failed_{role}")
            verify_result = "failed"
        else:
            verify_result = "passed"

        if output.confidence < agent._config.confidence_threshold and output.status == "success":
            output = output.model_copy(update={"status": "partial"})
            agent_metrics.record_human_escalation(f"low_confidence_{role}")
        return output, verify_result

    @traceable(name="agent.run")
    async def execute_with_guardrails(
        self,
        agent: BaseAgent,
        input: AgentInput,
    ) -> AgentOutput:
        """Domain agent path: JIT context → secret redaction → run → schema → verify."""
        role = agent._config.role
        agent_metrics.record_node_execution(role, "harness_execute")

        dirty = self._reject_dirty_handoff(role=role, input=input)
        if dirty is not None:
            return dirty

        prepared = await self._prepare_agent_input(agent, input, role=role)
        if isinstance(prepared, AgentOutput):
            return prepared
        input = prepared

        try:
            output = await asyncio.wait_for(
                agent.run(input),
                timeout=agent._config.timeout_seconds,
            )
        except TimeoutError:
            agent_metrics.record_error(role, "TimeoutError")
            output = AgentOutput(
                task_id=input.task_id,
                status="failure",
                confidence=0.0,
                output=_empty_output_payload(input.task_id),
                error_message=f"Agent timed out after {agent._config.timeout_seconds}s",
            )
            _stamp_agent_run_span(role=role, status=output.status, verify_result="error")
            return output
        except Exception as exc:
            agent_metrics.record_error(role, type(exc).__name__)
            logger.exception("harness.run_failed", agent=role, task_id=str(input.task_id))
            output = AgentOutput(
                task_id=input.task_id,
                status="failure",
                confidence=0.0,
                output=_empty_output_payload(input.task_id),
                error_message=str(exc),
            )
            _stamp_agent_run_span(role=role, status=output.status, verify_result="error")
            return output

        output, verify_result = await self._verify_after_run(agent, output, role=role)
        _stamp_agent_run_span(role=role, status=output.status, verify_result=verify_result)
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
        """Compact dialog at 80% tier budget; preserve goal/plan/last_results (065).

        Graph agents carry dialog as ``dialog_window_json`` (DialogTurnWindow). Legacy
        ``history`` plain text remains supported for non-graph callers.
        """
        dialog_key, dialog_text = _dialog_for_compact(input.context)
        if dialog_text is None:
            return input
        thread_id = (input.context.get("_thread_id") or str(input.task_id)).strip()
        user_id = input.context.get("_user_id")
        result = await self._context_builder.compact(
            CompactRequest(
                dialog=dialog_text,
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
            "goal": result.goal,
            "plan": result.plan,
            "last_results": result.last_results,
        }
        if dialog_key == "dialog_window_json":
            updated["dialog_window_json"] = _compacted_dialog_window_json(
                thread_id=thread_id,
                compacted_dialog=result.dialog,
            )
        else:
            updated["history"] = result.dialog
        return input.model_copy(update={"context": updated})


def _dialog_for_compact(context: dict[str, str]) -> tuple[str, str | None]:
    """Pick the dialog key and flat text for ContextBuilder.compact."""
    raw_window = context.get("dialog_window_json")
    if isinstance(raw_window, str) and raw_window.strip():
        flat = _flatten_dialog_window_json(raw_window)
        if flat:
            return "dialog_window_json", flat
    history = context.get("history")
    if isinstance(history, str) and history.strip():
        return "history", history
    return "history", None


def _flatten_dialog_window_json(raw: str) -> str:
    """Serialize a DialogTurnWindow JSON payload into role:content lines."""
    from palatium_ai.domain.memory.turns import DialogTurnWindow

    try:
        window = DialogTurnWindow.model_validate_json(raw)
    except Exception:  # noqa: BLE001  # malformed window → skip compact, do not brick the turn
        return ""
    lines = [f"{turn.role}: {turn.content}" for turn in window.turns if turn.content.strip()]
    return "\n".join(lines)


def _compacted_dialog_window_json(*, thread_id: str, compacted_dialog: str) -> str:
    """Replace the window with a single system turn holding the compact summary."""
    from uuid import uuid4

    from palatium_ai.domain.memory.turns import DialogTurn, DialogTurnWindow

    text = compacted_dialog.strip() or "(compacted)"
    window = DialogTurnWindow(
        thread_id=thread_id,
        turns=(
            DialogTurn(
                id=uuid4(),
                thread_id=thread_id,
                role="system",
                content=text[:50_000],
                seq=0,
            ),
        ),
        limit=12,
    )
    return window.model_dump_json()


def _empty_output_payload(task_id: object) -> BaseModel:
    from pydantic import BaseModel, Field

    class _HarnessFailureOutput(BaseModel):
        model_config = {"frozen": True}

        task_id: str = Field(default_factory=lambda: str(task_id))

    return _HarnessFailureOutput()


def _is_retryable_llm_call(exc: BaseException) -> bool:
    """Shared retry predicate — permanent / budget / circuit never retry (W8.3)."""
    if isinstance(exc, (CostBudgetExceededError, StructuredOutputUnsupportedError, CircuitOpenError)):
        return False
    return is_transient_llm_error(exc)


def _resolve_llm_controls(
    config: AgentConfig,
    *,
    reasoning_effort: ReasoningEffort | None,
    verbosity: TextVerbosity | None,
) -> tuple[ReasoningEffort, TextVerbosity | None]:
    """Resolve depth vs length dials independently (call override > config > tier)."""
    effort = (
        reasoning_effort
        if reasoning_effort is not None
        else config.reasoning_effort
        if config.reasoning_effort is not None
        else ReasoningEffortPolicy.for_model_tier(config.model_tier)
    )
    verb = verbosity if verbosity is not None else config.verbosity
    return effort, verb


def _prompt_version_for_role(role: str) -> str:
    """SHA-16 of the agent prompts.py (W8.7) — logged on every LLM call."""
    from pathlib import Path

    from palatium_ai.application.agents.evals.constitution_hash import prompt_file_version

    agents_root = Path(__file__).resolve().parent
    if role == "context_enricher":
        candidates = (
            agents_root / "context_enricher" / "continuation" / "prompts.py",
            agents_root / "context_enricher" / "weaving" / "prompts.py",
        )
    else:
        candidates = (agents_root / role / "prompts.py",)
    for path in candidates:
        if path.is_file():
            return prompt_file_version(path)
    return "unknown"


def _stamp_agent_run_span(*, role: str, status: str, verify_result: str) -> None:
    """Attach role/status/verify_result to the current ``agent.run`` span (W8.2)."""
    try:
        from opentelemetry import trace
    except ImportError:  # pragma: no cover
        return
    span = trace.get_current_span()
    if span is None or not span.is_recording():
        return
    set_attributes = getattr(span, "set_attributes", None)
    if not callable(set_attributes):
        return
    set_attributes(
        {
            "agent.role": role,
            "agent.status": status,
            "agent.verify_result": verify_result,
        }
    )

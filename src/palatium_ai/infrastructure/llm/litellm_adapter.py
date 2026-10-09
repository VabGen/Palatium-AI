# src/palatium_ai/infrastructure/llm/litellm_adapter.py

"""LiteLLM-адаптер — единая реализация LLMPort для всех провайдеров."""

from __future__ import annotations

import math

from typing import TYPE_CHECKING, Any, cast

import structlog

from litellm import acompletion

from palatium_ai.core.logging.redact import redact_text
from palatium_ai.domain.llm.errors import StructuredOutputUnsupportedError
from palatium_ai.domain.llm.models import (
    ChatMessage,
    LLMCompletion,
    LLMResponseFormat,
    LLMStreamDelta,
    LLMUsage,
)
from palatium_ai.domain.llm.structured_output import response_model_for_schema
from palatium_ai.infrastructure.llm.litellm_model import resolve_litellm_model

if TYPE_CHECKING:
    from collections.abc import AsyncIterator

    from pydantic import BaseModel

    from palatium_ai.core.config.llm.base import LLMProviderConfig

logger = structlog.get_logger(__name__)

_UNSUPPORTED_MARKERS = ("not support", "unsupported", "unrecognized", "unknown parameter", "invalid parameter")
_FORMAT_MARKERS = ("response_format", "json_schema", "strict")


def is_structured_output_unsupported(exc: BaseException) -> bool:
    """True only for an explicit provider refusal of json_schema / strict mode.

    ``invalid_schema`` is our payload, not a missing capability — callers must
    see that error instead of falling back to ``json_object``.
    """
    message = str(exc).lower()
    if "invalid_schema" in message or "invalid schema" in message:
        return False
    mentions_format = any(token in message for token in _FORMAT_MARKERS)
    refused = any(token in message for token in _UNSUPPORTED_MARKERS)
    return mentions_format and refused


def build_provider_response_format(
    response_format: LLMResponseFormat | None,
    response_model: type[BaseModel] | None,
) -> dict[str, Any] | None:
    """Map the domain mode onto an OpenAI-compatible ``response_format`` payload."""
    model = response_model_for_schema(response_format, response_model)
    if model is not None:
        return {
            "type": "json_schema",
            "json_schema": {
                "name": model.__name__,
                "schema": model.model_json_schema(),
                "strict": True,
            },
        }
    if response_format == "json_object":
        return {"type": "json_object"}
    return None


def _raise_if_unsupported(exc: Exception, *, response_format: LLMResponseFormat | None) -> None:
    if response_format == "json_schema" and is_structured_output_unsupported(exc):
        logger.warning(
            "llm.structured_output_unsupported",
            error=redact_text(str(exc)),
        )
        raise StructuredOutputUnsupportedError(redact_text(str(exc))) from exc


def _to_litellm_messages(messages: list[ChatMessage]) -> list[dict[str, object]]:
    """Map domain messages; attach Anthropic-style cache_control on system prefixes."""
    out: list[dict[str, object]] = []
    for message in messages:
        if message.cache_control is not None and message.role == "system":
            out.append(
                {
                    "role": message.role,
                    "content": [
                        {
                            "type": "text",
                            "text": message.content,
                            "cache_control": {"type": message.cache_control},
                        }
                    ],
                }
            )
        else:
            out.append({"role": message.role, "content": message.content})
    return out


def _parse_usage(usage_obj: object | None) -> LLMUsage:
    if usage_obj is None:
        return LLMUsage()
    if isinstance(usage_obj, dict):
        prompt = usage_obj.get("prompt_tokens", 0)
        completion = usage_obj.get("completion_tokens", 0)
        total = usage_obj.get("total_tokens", 0)
    else:
        prompt = getattr(usage_obj, "prompt_tokens", 0)
        completion = getattr(usage_obj, "completion_tokens", 0)
        total = getattr(usage_obj, "total_tokens", 0)
    prompt_tokens = prompt if isinstance(prompt, int) else 0
    completion_tokens = completion if isinstance(completion, int) else 0
    total_tokens = total if isinstance(total, int) else 0
    if total_tokens <= 0:
        total_tokens = prompt_tokens + completion_tokens
    return LLMUsage(
        prompt_tokens=prompt_tokens,
        completion_tokens=completion_tokens,
        total_tokens=total_tokens,
    )


def _parse_response_cost(response: object) -> float | None:
    """Provider-reported USD cost for the call, or None when none was reported.

    LiteLLM surfaces the gateway's ``x-litellm-response-cost`` through ``_hidden_params``.
    A gateway routing opaque tier aliases is the only component that can price the call,
    so this value is authoritative over any local price table. Absent, non-numeric or
    negative values mean "not reported" — never invent a rate (050).
    """
    hidden = getattr(response, "_hidden_params", None)
    if not isinstance(hidden, dict):
        return None
    raw = hidden.get("response_cost")
    if isinstance(raw, bool) or not isinstance(raw, int | float):
        return None
    cost = float(raw)
    if not math.isfinite(cost) or cost < 0.0:
        return None
    return cost


def _parse_completion(response: object) -> LLMCompletion:
    content = ""
    finish_reason: str | None = None
    model = ""

    choices = getattr(response, "choices", None)
    if isinstance(choices, list) and choices:
        first_choice = choices[0]
        message = getattr(first_choice, "message", None)
        if message is not None:
            raw_content = getattr(message, "content", None)
            if isinstance(raw_content, str):
                content = raw_content
        raw_finish = getattr(first_choice, "finish_reason", None)
        if isinstance(raw_finish, str):
            finish_reason = raw_finish

    raw_model = getattr(response, "model", None)
    if isinstance(raw_model, str):
        model = raw_model

    usage = _parse_usage(getattr(response, "usage", None))
    return LLMCompletion(
        content=content,
        model=model,
        usage=usage,
        finish_reason=finish_reason,
        cost_usd=_parse_response_cost(response),
    )


def _parse_stream_delta(chunk: object) -> LLMStreamDelta:
    content = ""
    finish_reason: str | None = None
    model: str | None = None

    choices = getattr(chunk, "choices", None)
    if isinstance(choices, list) and choices:
        first_choice = choices[0]
        delta = getattr(first_choice, "delta", None)
        if delta is not None:
            raw_content = getattr(delta, "content", None)
            if isinstance(raw_content, str):
                content = raw_content
        raw_finish = getattr(first_choice, "finish_reason", None)
        if isinstance(raw_finish, str):
            finish_reason = raw_finish

    raw_model = getattr(chunk, "model", None)
    if isinstance(raw_model, str) and raw_model.strip():
        model = raw_model.strip()

    usage_raw = getattr(chunk, "usage", None)
    usage = _parse_usage(usage_raw) if usage_raw is not None else None
    # Final usage chunk often has empty choices; treat zeroed usage as absent.
    if usage is not None and usage.prompt_tokens == 0 and usage.completion_tokens == 0:
        usage = None

    return LLMStreamDelta(
        content=content,
        finish_reason=finish_reason,
        usage=usage,
        cost_usd=_parse_response_cost(chunk),
        model=model,
    )


class LiteLLMAdapter:
    """Реализация LLMPort через LiteLLM для любого LLMProviderConfig."""

    def __init__(self, config: LLMProviderConfig) -> None:
        self._config = config
        self._api_key = config.get_api_key()
        self._base_url = config.get_base_url()
        self._default_model = config.get_default_model()
        self._provider = config.provider_name
        self._timeout_seconds = config.get_timeout_seconds()

    def _build_params(
        self,
        *,
        model: str | None,
        temperature: float | None,
        max_tokens: int | None,
        response_format: LLMResponseFormat | None,
        response_model: type[BaseModel] | None = None,
    ) -> dict[str, Any]:
        """Shared LiteLLM kwargs (``stream`` passed as a Literal at the call site)."""
        resolved_model = resolve_litellm_model(
            provider=self._provider,
            model=model or self._default_model,
            base_url=self._base_url,
        )
        # Vendor boundary: LiteLLM's acompletion kwargs are typed per-arg; dict[str, Any]
        # is the supported unpack form (dict[str, object] fails reportArgumentType).
        params: dict[str, Any] = {
            "model": resolved_model,
            "api_key": self._api_key,
            "api_base": self._base_url,
        }
        if self._timeout_seconds is not None:
            # Forward the provider timeout so a hung completion cannot outlive the agent (020/050).
            params["timeout"] = self._timeout_seconds
        if temperature is not None:
            params["temperature"] = temperature
        if max_tokens is not None:
            params["max_tokens"] = max_tokens
        payload = build_provider_response_format(response_format, response_model)
        if payload is not None:
            params["response_format"] = payload
        return params

    async def generate(
        self,
        messages: list[ChatMessage],
        *,
        model: str | None = None,
        temperature: float | None = None,
        max_tokens: int | None = None,
        response_format: LLMResponseFormat | None = None,
        response_model: type[BaseModel] | None = None,
    ) -> LLMCompletion:
        """Выполняет синхронную генерацию текста."""
        params = self._build_params(
            model=model,
            temperature=temperature,
            max_tokens=max_tokens,
            response_format=response_format,
            response_model=response_model,
        )
        params["messages"] = _to_litellm_messages(messages)
        logger.debug(
            "LLM request",
            provider=self._provider,
            messages_count=len(messages),
            model=params["model"],
            response_format=response_format or "text",
        )
        try:
            # stream=False as Literal selects the non-streaming overload.
            response = await acompletion(**params, stream=False)
            completion = _parse_completion(response)
            logger.debug("LLM response received", provider=self._provider, model=completion.model)
            return completion
        except Exception as exc:
            _raise_if_unsupported(exc, response_format=response_format)
            logger.error(
                "LLM request failed",
                provider=self._provider,
                error=redact_text(str(exc)),
                exc_info=True,
            )
            raise

    async def generate_stream(
        self,
        messages: list[ChatMessage],
        *,
        model: str | None = None,
        temperature: float | None = None,
        max_tokens: int | None = None,
        response_format: LLMResponseFormat | None = None,
        response_model: type[BaseModel] | None = None,
    ) -> AsyncIterator[LLMStreamDelta]:
        """Возвращает поток частичных ответов."""
        from time import perf_counter

        from palatium_ai.core.observability.metrics import agent_metrics

        params = self._build_params(
            model=model,
            temperature=temperature,
            max_tokens=max_tokens,
            response_format=response_format,
            response_model=response_model,
        )
        # OpenAI-compatible: last chunk carries usage (and LiteLLM may attach cost).
        params["stream_options"] = {"include_usage": True}
        params["messages"] = _to_litellm_messages(messages)
        started = perf_counter()
        first_token = True
        # stream=True as Literal selects CustomStreamWrapper; cast keeps async-for typed
        # when the checker still widens the union return.
        try:
            raw_stream = await acompletion(**params, stream=True)
        except Exception as exc:
            _raise_if_unsupported(exc, response_format=response_format)
            raise
        stream = cast("AsyncIterator[object]", raw_stream)
        async for chunk in stream:
            delta = _parse_stream_delta(chunk)
            if first_token and delta.content:
                agent_metrics.record_llm_ttft(perf_counter() - started)
                first_token = False
            yield delta

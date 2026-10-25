# src/palatium_ai/infrastructure/llm/litellm_adapter.py

"""LiteLLM-адаптер — единая реализация LLMPort для всех провайдеров."""

from __future__ import annotations

import base64
import math

from typing import TYPE_CHECKING, Any, cast
from uuid import UUID

import structlog

from litellm import acompletion

from palatium_ai.core.logging.redact import redact_text
from palatium_ai.domain.llm.errors import StructuredOutputUnsupportedError, VisionUnsupportedError
from palatium_ai.domain.llm.models import (
    ChatMessage,
    ImagePart,
    LLMCompletion,
    LLMResponseFormat,
    LLMStreamDelta,
    LLMUsage,
)
from palatium_ai.domain.llm.structured_output import response_model_for_schema, strict_json_schema
from palatium_ai.infrastructure.llm.citation_mapping import citations_from_response
from palatium_ai.infrastructure.llm.litellm_model import resolve_litellm_model
from palatium_ai.infrastructure.llm.shared_transport import shared_client_session

if TYPE_CHECKING:
    from collections.abc import AsyncIterator

    from pydantic import BaseModel

    from palatium_ai.core.config.llm.base import LLMProviderConfig
    from palatium_ai.domain.ports.vision import VisionImageSourcePort

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
                # strict: True only binds when the schema actually matches the strict
                # contract (all props required, additionalProperties: false, no defaults).
                "schema": strict_json_schema(model),
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


def _to_litellm_messages(
    messages: list[ChatMessage],
    *,
    image_urls: dict[UUID, str] | None = None,
) -> list[dict[str, object]]:
    """Map domain messages; attach Anthropic-style cache_control on system prefixes.

    ``image_urls`` carries already-resolved data URLs for the turn's image parts. A
    part without a resolved URL is a hard error, never a silently text-only message:
    the model would answer "the picture is empty" and sound certain about it (ADR 0007).
    """
    resolved = image_urls or {}
    out: list[dict[str, object]] = []
    for message in messages:
        images = [_image_url_part(part, resolved) for part in message.image_parts]
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
        elif images:
            out.append(
                {
                    "role": message.role,
                    "content": [{"type": "text", "text": message.content}, *images],
                }
            )
        else:
            out.append({"role": message.role, "content": message.content})
    return out


def _image_url_part(part: ImagePart, resolved: dict[UUID, str]) -> dict[str, object]:
    """One OpenAI-compatible image part from a resolved data URL."""
    url = resolved.get(part.attachment_id)
    if not url:
        raise VisionUnsupportedError(
            f"no vision image source resolved attachment {part.attachment_id}",
        )
    return {"type": "image_url", "image_url": {"url": url}}


def _data_url(data: bytes, *, mime_type: str) -> str:
    """Inline data URL: no second upload round-trip and no attacker-controlled URL."""
    encoded = base64.b64encode(data).decode("ascii")
    return f"data:{mime_type};base64,{encoded}"


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


def _coerce_cost_usd(raw: object) -> float | None:
    """Normalize a numeric cost; reject bool/NaN/negative."""
    if isinstance(raw, bool) or not isinstance(raw, int | float):
        return None
    cost = float(raw)
    if not math.isfinite(cost) or cost < 0.0:
        return None
    return cost


def _parse_response_cost(response: object) -> float | None:
    """Provider-reported USD cost for the call, or None when none was reported.

    LiteLLM surfaces the gateway's ``x-litellm-response-cost`` through ``_hidden_params``.
    Fallback: ``litellm.completion_cost`` after tier registration (Phase 3). Absent,
    non-numeric or negative values mean "not reported" — never invent a rate (050).
    """
    hidden = getattr(response, "_hidden_params", None)
    from_hidden = _coerce_cost_usd(hidden.get("response_cost")) if isinstance(hidden, dict) else None
    if from_hidden is not None and from_hidden > 0.0:
        return from_hidden

    try:
        import litellm

        computed = litellm.completion_cost(completion_response=response)
    except Exception as exc:  # noqa: BLE001  # cost is best-effort telemetry; the LLM call must not fail (040)
        # Cost is best-effort telemetry: a missing price card must never fail the LLM
        # call. LiteLLM raises ModelNotMappedError for gateway tier aliases that are
        # absent from its table — the gateway is the only component that can price
        # them, so an unreported cost stays None (never invent a rate, 050).
        logger.debug(
            "llm.cost.compute_failed",
            reason="model_not_in_price_table",
            detail=redact_text(str(exc)),
        )
        return from_hidden
    from_table = _coerce_cost_usd(computed)
    if from_table is not None and from_table > 0.0:
        return from_table
    return from_hidden if from_hidden is not None else from_table


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
        citations=citations_from_response(response),
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

    def __init__(
        self,
        config: LLMProviderConfig,
        *,
        vision_model: str | None = None,
        image_source: VisionImageSourcePort | None = None,
    ) -> None:
        self._config = config
        self._api_key = config.get_api_key()
        self._base_url = config.get_base_url()
        self._default_model = config.get_default_model()
        self._provider = config.provider_name
        self._timeout_seconds = config.get_timeout_seconds()
        # ADR 0007: the vision alias is provider-level config, not an agent tier — an
        # image call must not inherit ``tier-small`` from the calling agent.
        self._vision_model = (vision_model or "").strip() or None
        self._image_source = image_source

    async def _vision_image_urls(self, messages: list[ChatMessage]) -> dict[UUID, str] | None:
        """Resolve image parts into data URLs; ``None`` when the call carries no images.

        Every refusal is typed and happens before the provider call: an unconfigured
        alias, a missing source, or a blob that fails storage checks (020, ADR 0007).
        """
        parts = [part for message in messages for part in message.image_parts]
        if not parts:
            return None
        if self._vision_model is None:
            raise VisionUnsupportedError("LLM_VISION_MODEL is not configured")
        if self._image_source is None:
            raise VisionUnsupportedError("vision image source is not wired")

        urls: dict[UUID, str] = {}
        total_bytes = 0
        for part in parts:
            data = await self._image_source.read(part.attachment_id, expected_mime=part.mime)
            urls[part.attachment_id] = _data_url(data, mime_type=part.mime)
            total_bytes += len(data)
        # Counts and sizes only: the payload itself must never reach a log (020).
        logger.debug(
            "LLM vision request",
            provider=self._provider,
            images=len(parts),
            image_bytes=total_bytes,
        )
        return urls

    def _build_params(
        self,
        *,
        model: str | None,
        temperature: float | None,
        max_tokens: int | None,
        response_format: LLMResponseFormat | None,
        response_model: type[BaseModel] | None = None,
        timeout_seconds: float | None = None,
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
        # A shared session is what keeps LiteLLM from opening (and leaking) one aiohttp
        # session per request; the loop-scoped registry lives in shared_transport.
        params["shared_session"] = shared_client_session()
        # Per-call dynamic timeout wins over provider default (Phase 4).
        effective_timeout = timeout_seconds if timeout_seconds is not None else self._timeout_seconds
        if effective_timeout is not None:
            params["timeout"] = effective_timeout
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
        timeout_seconds: float | None = None,
    ) -> LLMCompletion:
        """Выполняет синхронную генерацию текста (или vision-вызов при image_parts)."""
        image_urls = await self._vision_image_urls(messages)
        params = self._build_params(
            model=self._vision_model if image_urls else model,
            temperature=temperature,
            max_tokens=max_tokens,
            response_format=response_format,
            response_model=response_model,
            timeout_seconds=timeout_seconds,
        )
        params["messages"] = _to_litellm_messages(messages, image_urls=image_urls)
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
        timeout_seconds: float | None = None,
    ) -> AsyncIterator[LLMStreamDelta]:
        """Возвращает поток частичных ответов (vision-вызов при image_parts)."""
        from time import perf_counter

        from palatium_ai.core.observability.metrics import agent_metrics

        image_urls = await self._vision_image_urls(messages)
        params = self._build_params(
            model=self._vision_model if image_urls else model,
            temperature=temperature,
            max_tokens=max_tokens,
            response_format=response_format,
            response_model=response_model,
            timeout_seconds=timeout_seconds,
        )
        # OpenAI-compatible: last chunk carries usage (and LiteLLM may attach cost).
        params["stream_options"] = {"include_usage": True}
        params["messages"] = _to_litellm_messages(messages, image_urls=image_urls)
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

# src/palatium_ai/infrastructure/llm/litellm_adapter.py

"""LiteLLM-адаптер — единая реализация LLMPort для всех провайдеров."""

from __future__ import annotations

from typing import TYPE_CHECKING

import structlog

from litellm import acompletion

from palatium_ai.domain.llm.models import (
    ChatMessage,
    LLMCompletion,
    LLMResponseFormat,
    LLMStreamDelta,
    LLMUsage,
)
from palatium_ai.infrastructure.llm.litellm_model import resolve_litellm_model

if TYPE_CHECKING:
    from collections.abc import AsyncIterator

    from palatium_ai.core.config.llm.base import LLMProviderConfig

logger = structlog.get_logger(__name__)


def _to_litellm_messages(messages: list[ChatMessage]) -> list[dict[str, str]]:
    return [{"role": message.role, "content": message.content} for message in messages]


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
    return LLMCompletion(content=content, model=model, usage=usage, finish_reason=finish_reason)


def _parse_stream_delta(chunk: object) -> LLMStreamDelta:
    content = ""
    finish_reason: str | None = None

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

    return LLMStreamDelta(content=content, finish_reason=finish_reason)


class LiteLLMAdapter:
    """Реализация LLMPort через LiteLLM для любого LLMProviderConfig."""

    def __init__(self, config: LLMProviderConfig) -> None:
        self._config = config
        self._api_key = config.get_api_key()
        self._base_url = config.get_base_url()
        self._default_model = config.get_default_model()
        self._provider = config.provider_name

    def _build_params(
        self,
        *,
        model: str | None,
        temperature: float | None,
        max_tokens: int | None,
        stream: bool,
        response_format: LLMResponseFormat | None,
    ) -> dict[str, object]:
        resolved_model = resolve_litellm_model(
            provider=self._provider,
            model=model or self._default_model,
            base_url=self._base_url,
        )
        params: dict[str, object] = {
            "model": resolved_model,
            "api_key": self._api_key,
            "api_base": self._base_url,
            "stream": stream,
        }
        if temperature is not None:
            params["temperature"] = temperature
        if max_tokens is not None:
            params["max_tokens"] = max_tokens
        if response_format == "json_object":
            # OpenAI-compatible structured mode; providers that ignore it still get codec parse.
            params["response_format"] = {"type": "json_object"}
        return params

    async def generate(
        self,
        messages: list[ChatMessage],
        *,
        model: str | None = None,
        temperature: float | None = None,
        max_tokens: int | None = None,
        response_format: LLMResponseFormat | None = None,
    ) -> LLMCompletion:
        """Выполняет синхронную генерацию текста."""
        params = self._build_params(
            model=model,
            temperature=temperature,
            max_tokens=max_tokens,
            stream=False,
            response_format=response_format,
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
            response = await acompletion(**params)
            completion = _parse_completion(response)
            logger.debug("LLM response received", provider=self._provider, model=completion.model)
            return completion
        except Exception as exc:
            logger.error("LLM request failed", provider=self._provider, error=str(exc), exc_info=True)
            raise

    async def generate_stream(
        self,
        messages: list[ChatMessage],
        *,
        model: str | None = None,
        temperature: float | None = None,
        max_tokens: int | None = None,
        response_format: LLMResponseFormat | None = None,
    ) -> AsyncIterator[LLMStreamDelta]:
        """Возвращает поток частичных ответов."""
        params = self._build_params(
            model=model,
            temperature=temperature,
            max_tokens=max_tokens,
            stream=True,
            response_format=response_format,
        )
        params["messages"] = _to_litellm_messages(messages)
        stream = await acompletion(**params)
        async for chunk in stream:
            yield _parse_stream_delta(chunk)

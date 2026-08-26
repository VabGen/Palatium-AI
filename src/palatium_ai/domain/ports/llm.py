# src/palatium_ai/domain/ports/llm.py

"""Порт доступа к LLM-провайдерам."""

from __future__ import annotations

from typing import TYPE_CHECKING, Protocol

if TYPE_CHECKING:
    from collections.abc import AsyncIterator

    from palatium_ai.domain.llm.models import (
        ChatMessage,
        LLMCompletion,
        LLMResponseFormat,
        LLMStreamDelta,
    )


class LLMPort(Protocol):
    """Контракт генерации текста через LLM."""

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
        ...

    def generate_stream(
        self,
        messages: list[ChatMessage],
        *,
        model: str | None = None,
        temperature: float | None = None,
        max_tokens: int | None = None,
        response_format: LLMResponseFormat | None = None,
    ) -> AsyncIterator[LLMStreamDelta]:
        """Возвращает поток частичных ответов."""
        ...

# src/palatium_ai/application/agents/evals/static_llm.py

"""Static LLM port for cassette evals (075)."""

from __future__ import annotations

from collections.abc import AsyncIterator

from palatium_ai.domain.llm.models import ChatMessage, LLMCompletion, LLMResponseFormat, LLMStreamDelta


class StaticLLMPort:
    """Minimal LLMPort returning a fixed response."""

    def __init__(self, content: str, *, model: str = "cassette-model") -> None:
        self._content = content
        self._model = model
        self.calls: list[list[ChatMessage]] = []

    async def generate(
        self,
        messages: list[ChatMessage],
        *,
        model: str | None = None,
        temperature: float | None = None,
        max_tokens: int | None = None,
        response_format: LLMResponseFormat | None = None,
        response_model: object = None,
    ) -> LLMCompletion:
        self.calls.append(list(messages))
        _ = temperature, max_tokens, response_format, response_model
        return LLMCompletion(content=self._content, model=model or self._model)

    async def generate_stream(
        self,
        messages: list[ChatMessage],
        *,
        model: str | None = None,
        temperature: float | None = None,
        max_tokens: int | None = None,
        response_format: LLMResponseFormat | None = None,
        response_model: object = None,
    ) -> AsyncIterator[LLMStreamDelta]:
        completion = await self.generate(
            messages,
            model=model,
            temperature=temperature,
            max_tokens=max_tokens,
            response_format=response_format,
            response_model=response_model,
        )
        yield LLMStreamDelta(
            content=completion.content,
            usage=completion.usage,
            cost_usd=completion.cost_usd,
            model=completion.model,
        )


class SequentialStaticLLMPort(StaticLLMPort):
    """Static LLM port that dequeues cassette responses in order."""

    def __init__(self, responses: list[str], *, model: str = "cassette-model") -> None:
        super().__init__(responses[0] if responses else "{}", model=model)
        self._responses = list(responses)
        self._index = 0

    async def generate(
        self,
        messages: list[ChatMessage],
        *,
        model: str | None = None,
        temperature: float | None = None,
        max_tokens: int | None = None,
        response_format: LLMResponseFormat | None = None,
        response_model: object = None,
    ) -> LLMCompletion:
        if self._index >= len(self._responses):
            return await super().generate(
                messages,
                model=model,
                temperature=temperature,
                max_tokens=max_tokens,
                response_format=response_format,
                response_model=response_model,
            )
        self.calls.append(list(messages))
        content = self._responses[self._index]
        self._index += 1
        _ = temperature, max_tokens, response_format, response_model
        return LLMCompletion(content=content, model=model or self._model)

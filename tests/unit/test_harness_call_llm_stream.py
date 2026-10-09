"""Harness.call_llm_stream accumulates deltas and forwards on_delta."""

from __future__ import annotations

from collections.abc import AsyncIterator
from types import SimpleNamespace

import pytest

from palatium_ai.application.agents.formatter import FORMATTER_CONFIG
from palatium_ai.application.agents.harness import Harness
from palatium_ai.core.observability.turn_tokens import get_turn_token_collector, turn_token_usage
from palatium_ai.domain.llm.models import (
    ChatMessage,
    LLMCompletion,
    LLMResponseFormat,
    LLMStreamDelta,
    LLMUsage,
)
from palatium_ai.infrastructure.llm.litellm_adapter import _parse_stream_delta


class _StreamingLLM:
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
        _ = messages, temperature, max_tokens, response_format, response_model
        return LLMCompletion(content="{}", model=model or "m")

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
        _ = messages, model, temperature, max_tokens, response_format, response_model
        for piece in ('{"a":', "1}"):
            yield LLMStreamDelta(content=piece)
        yield LLMStreamDelta(
            usage=LLMUsage(prompt_tokens=40, completion_tokens=12, total_tokens=52),
            cost_usd=0.0031,
            model="tier-mid",
        )


@pytest.mark.asyncio()
async def test_call_llm_stream_forwards_deltas_and_joins() -> None:
    seen: list[str] = []

    async def on_delta(chunk: str) -> None:
        seen.append(chunk)

    harness = Harness(llm=_StreamingLLM())
    completion = await harness.call_llm_stream(
        FORMATTER_CONFIG,
        [ChatMessage(role="user", content="x")],
        response_format="json_object",
        on_delta=on_delta,
    )
    assert completion.content == '{"a":1}'
    assert seen == ['{"a":', "1}"]
    assert completion.usage.prompt_tokens == 40
    assert completion.usage.completion_tokens == 12
    assert completion.cost_usd == 0.0031
    assert completion.model == "tier-mid"


@pytest.mark.asyncio()
async def test_call_llm_stream_records_turn_tokens_and_cost() -> None:
    harness = Harness(llm=_StreamingLLM())
    with turn_token_usage() as tokens:
        await harness.call_llm_stream(
            FORMATTER_CONFIG,
            [ChatMessage(role="user", content="x")],
            response_format="json_object",
        )
        fields = tokens.as_log_fields()
    assert fields["llm_calls"] == 1
    assert fields["token_total"] == 52
    assert fields["cost_usd_total"] == 0.0031
    assert get_turn_token_collector() is None


def test_parse_stream_delta_carries_usage_and_cost() -> None:
    chunk = SimpleNamespace(
        choices=[],
        model="tier-mid",
        usage=SimpleNamespace(prompt_tokens=11, completion_tokens=7, total_tokens=18),
        _hidden_params={"response_cost": 0.002},
    )
    delta = _parse_stream_delta(chunk)
    assert delta.content == ""
    assert delta.usage is not None
    assert delta.usage.prompt_tokens == 11
    assert delta.cost_usd == 0.002
    assert delta.model == "tier-mid"


def test_parse_stream_delta_ignores_zero_usage_chunk() -> None:
    chunk = SimpleNamespace(
        choices=[SimpleNamespace(delta=SimpleNamespace(content="hi"), finish_reason=None)],
        usage=SimpleNamespace(prompt_tokens=0, completion_tokens=0, total_tokens=0),
    )
    delta = _parse_stream_delta(chunk)
    assert delta.content == "hi"
    assert delta.usage is None

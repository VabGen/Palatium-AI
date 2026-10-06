"""Cost resolution: the gateway-reported cost wins over the local price table (040).

Regression (observed in the docker stack): the platform sends opaque tier aliases
(``tier-small``) to the LiteLLM gateway, which resolves them to a real model. The local
estimator was fed the alias, raised ``BadRequestError`` on every call, and the error was
swallowed — ``palatium_agent_cost_usd_total`` stayed at zero forever.
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from types import SimpleNamespace

import pytest

from palatium_ai.application.agents.harness import Harness, _resolve_cost_usd
from palatium_ai.application.agents.researcher import RESEARCHER_CONFIG
from palatium_ai.domain.llm.models import ChatMessage, LLMCompletion, LLMResponseFormat, LLMStreamDelta, LLMUsage
from palatium_ai.infrastructure.llm.litellm_adapter import _parse_completion, _parse_response_cost


class _RecordingEstimator:
    """Stands in for the LiteLLM price-table estimator and records how it was called."""

    def __init__(self, value: float = 0.0) -> None:
        self.value = value
        self.calls: list[dict[str, object]] = []

    def __call__(self, *, model: str, prompt_tokens: int, completion_tokens: int) -> float:
        self.calls.append({"model": model, "prompt_tokens": prompt_tokens, "completion_tokens": completion_tokens})
        return self.value


class _CostReportingLLM:
    """LLMPort double that reports a provider cost, like the real gateway adapter does."""

    def __init__(self, *, cost_usd: float | None) -> None:
        self._cost_usd = cost_usd
        self.calls = 0

    async def generate(
        self,
        messages: list[ChatMessage],
        *,
        model: str | None = None,
        temperature: float | None = None,
        max_tokens: int | None = None,
        response_format: LLMResponseFormat | None = None,
    ) -> LLMCompletion:
        _ = messages, temperature, max_tokens, response_format
        self.calls += 1
        return LLMCompletion(
            content="ok",
            model=model or "tier-small",
            usage=LLMUsage(prompt_tokens=10, completion_tokens=5, total_tokens=15),
            cost_usd=self._cost_usd,
        )

    async def generate_stream(
        self,
        messages: list[ChatMessage],
        *,
        model: str | None = None,
        temperature: float | None = None,
        max_tokens: int | None = None,
        response_format: LLMResponseFormat | None = None,
    ) -> AsyncIterator[LLMStreamDelta]:  # pragma: no cover - unused by these tests
        _ = messages, model, temperature, max_tokens, response_format
        yield LLMStreamDelta(content="ok")


def _completion(*, cost_usd: float | None, model: str = "tier-small") -> LLMCompletion:
    return LLMCompletion(content="ok", model=model, cost_usd=cost_usd)


def test_reported_cost_wins_and_estimator_is_not_consulted() -> None:
    estimator = _RecordingEstimator(value=99.0)
    cost = _resolve_cost_usd(completion=_completion(cost_usd=0.0042), fallback_model="tier-small", estimator=estimator)
    assert cost == 0.0042
    assert estimator.calls == []


def test_reported_zero_cost_is_respected_not_treated_as_missing() -> None:
    """A priced-but-free call reports 0.0; that is still authoritative, not 'absent'."""
    estimator = _RecordingEstimator(value=99.0)
    cost = _resolve_cost_usd(completion=_completion(cost_usd=0.0), fallback_model="tier-small", estimator=estimator)
    assert cost == 0.0
    assert estimator.calls == []


def test_missing_cost_falls_back_to_estimator() -> None:
    estimator = _RecordingEstimator(value=0.01)
    cost = _resolve_cost_usd(completion=_completion(cost_usd=None), fallback_model="tier-small", estimator=estimator)
    assert cost == 0.01
    assert estimator.calls == [{"model": "tier-small", "prompt_tokens": 0, "completion_tokens": 0}]


def test_missing_cost_without_estimator_is_zero() -> None:
    assert _resolve_cost_usd(completion=_completion(cost_usd=None), fallback_model="m", estimator=None) == 0.0


@pytest.mark.parametrize(
    "hidden",
    (
        {},
        {"response_cost": None},
        {"response_cost": "0.5"},
        {"response_cost": True},
        {"response_cost": -1.0},
        {"response_cost": float("nan")},
        {"response_cost": float("inf")},
    ),
)
def test_unusable_hidden_cost_is_reported_as_absent(hidden: dict[str, object]) -> None:
    assert _parse_response_cost(SimpleNamespace(_hidden_params=hidden)) is None


def test_hidden_cost_is_extracted_from_response() -> None:
    response = SimpleNamespace(_hidden_params={"response_cost": 0.25})
    assert _parse_response_cost(response) == 0.25


def test_missing_or_non_dict_hidden_params_are_absent() -> None:
    assert _parse_response_cost(SimpleNamespace()) is None
    assert _parse_response_cost(SimpleNamespace(_hidden_params=["nope"])) is None


def test_parse_completion_carries_the_gateway_cost() -> None:
    response = SimpleNamespace(
        choices=[SimpleNamespace(message=SimpleNamespace(content="hello"), finish_reason="stop")],
        model="tier-small",
        usage=SimpleNamespace(prompt_tokens=3, completion_tokens=2, total_tokens=5),
        _hidden_params={"response_cost": 0.007},
    )
    completion = _parse_completion(response)
    assert completion.cost_usd == 0.007


@pytest.mark.asyncio()
async def test_harness_records_gateway_cost_without_estimator_call() -> None:
    estimator = _RecordingEstimator(value=99.0)
    llm = _CostReportingLLM(cost_usd=0.0042)
    harness = Harness(llm=llm, cost_estimator=estimator)

    completion = await harness.call_llm(RESEARCHER_CONFIG, [ChatMessage(role="user", content="hi")])

    assert completion.cost_usd == 0.0042
    assert estimator.calls == []

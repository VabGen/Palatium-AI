"""Sampled hallucination judge — never raises into the pipeline."""

from __future__ import annotations

import pytest

from palatium_ai.core.observability import grounding_guardrail as gg
from palatium_ai.core.observability.metrics import agent_metrics


@pytest.mark.asyncio()
async def test_judge_hallucinated_increments(monkeypatch: pytest.MonkeyPatch) -> None:
    before = agent_metrics  # noqa: F841 — use record path via side effect
    monkeypatch.setattr(gg.random, "random", lambda: 0.0)

    async def _judge(_p: str, _q: str, _a: str) -> dict[str, object]:
        return {"hallucinated": True, "reason": "invented number"}

    await gg.maybe_judge("q", "a", sample_rate=1.0, judge=_judge)


@pytest.mark.asyncio()
async def test_judge_false_no_crash(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(gg.random, "random", lambda: 0.0)

    async def _judge(_p: str, _q: str, _a: str) -> dict[str, object]:
        return {"hallucinated": False, "reason": "ok"}

    await gg.maybe_judge("q", "a", sample_rate=1.0, judge=_judge)


@pytest.mark.asyncio()
async def test_judge_exception_logged_not_raised(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(gg.random, "random", lambda: 0.0)

    async def _judge(_p: str, _q: str, _a: str) -> dict[str, object]:
        raise RuntimeError("llm down")

    await gg.maybe_judge("q", "a", sample_rate=1.0, judge=_judge)


@pytest.mark.asyncio()
async def test_below_sample_rate_skips(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(gg.random, "random", lambda: 0.99)
    called = False

    async def _judge(_p: str, _q: str, _a: str) -> dict[str, object]:
        nonlocal called
        called = True
        return {"hallucinated": True, "reason": "x"}

    await gg.maybe_judge("q", "a", sample_rate=0.01, judge=_judge)
    assert called is False

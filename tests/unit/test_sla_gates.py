# tests/unit/test_sla_gates.py

"""SLA gate math + structural benchmark corpus (Week 4 / production-audit P2)."""

from __future__ import annotations

import pytest

from palatium_ai.domain.sla.corpus import build_benchmark_corpus
from palatium_ai.domain.sla.gates import (
    evaluate_p95_latency_ms,
    evaluate_success_rate,
    percentile,
)


def test_percentile_p95() -> None:
    samples = [float(i) for i in range(1, 101)]
    assert percentile(samples, pct=50.0) == pytest.approx(50.5)
    assert percentile(samples, pct=95.0) == pytest.approx(95.05)


def test_success_rate_gate_pass_fail() -> None:
    ok = evaluate_success_rate(successes=90, total=100, min_rate=0.85)
    assert ok.passed is True
    assert ok.observed == pytest.approx(0.9)

    bad = evaluate_success_rate(successes=80, total=100, min_rate=0.85)
    assert bad.passed is False


def test_success_rate_requires_positive_total() -> None:
    result = evaluate_success_rate(successes=0, total=0)
    assert result.passed is False


def test_p95_latency_gate() -> None:
    # p95 falls in the high band (last 6 of 100 samples).
    samples = [10.0] * 94 + [200.0] * 6
    gate = evaluate_p95_latency_ms(samples_ms=samples, max_p95_ms=250.0)
    assert gate.passed is True
    assert gate.observed == pytest.approx(200.0)

    tight = evaluate_p95_latency_ms(samples_ms=samples, max_p95_ms=50.0)
    assert tight.passed is False


def test_benchmark_corpus_size_and_axes() -> None:
    corpus = build_benchmark_corpus(size=100)
    assert len(corpus) == 100
    kinds = {case.task_kind for case in corpus}
    assert "social_conversation" in kinds
    assert "tool_execution" in kinds
    assert any(case.requires_mcp for case in corpus)
    assert len({case.case_id for case in corpus}) == 100

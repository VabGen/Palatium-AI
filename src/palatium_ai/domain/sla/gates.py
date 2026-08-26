# src/palatium_ai/domain/sla/gates.py

"""Deterministic SLA gate evaluations (no I/O)."""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class SlaGateResult:
    """Outcome of one SLA gate check."""

    name: str
    passed: bool
    observed: float
    threshold: float
    detail: str


def percentile(samples: Sequence[float], *, pct: float) -> float:
    """Nearest-rank percentile for non-empty samples (pct in 0..100)."""
    if not samples:
        raise ValueError("percentile requires at least one sample")
    if pct < 0.0 or pct > 100.0:
        raise ValueError("pct must be in [0, 100]")
    ordered = sorted(float(x) for x in samples)
    if len(ordered) == 1:
        return ordered[0]
    rank = (pct / 100.0) * (len(ordered) - 1)
    low = int(rank)
    high = min(low + 1, len(ordered) - 1)
    weight = rank - low
    return ordered[low] * (1.0 - weight) + ordered[high] * weight


def evaluate_success_rate(
    *,
    successes: int,
    total: int,
    min_rate: float = 0.85,
    name: str = "benchmark_success_rate",
) -> SlaGateResult:
    """Pass when successes/total >= min_rate (DoD: 100+ tasks, >85%)."""
    if total <= 0:
        return SlaGateResult(
            name=name,
            passed=False,
            observed=0.0,
            threshold=min_rate,
            detail="total must be > 0",
        )
    if successes < 0 or successes > total:
        return SlaGateResult(
            name=name,
            passed=False,
            observed=0.0,
            threshold=min_rate,
            detail=f"invalid successes={successes} for total={total}",
        )
    rate = successes / total
    return SlaGateResult(
        name=name,
        passed=rate >= min_rate,
        observed=rate,
        threshold=min_rate,
        detail=f"{successes}/{total} = {rate:.4f}",
    )


def evaluate_p95_latency_ms(
    *,
    samples_ms: Sequence[float],
    max_p95_ms: float,
    name: str = "load_p95_latency_ms",
) -> SlaGateResult:
    """Pass when p95 latency is at or under max_p95_ms."""
    if not samples_ms:
        return SlaGateResult(
            name=name,
            passed=False,
            observed=0.0,
            threshold=max_p95_ms,
            detail="no latency samples",
        )
    p95 = percentile(samples_ms, pct=95.0)
    return SlaGateResult(
        name=name,
        passed=p95 <= max_p95_ms,
        observed=p95,
        threshold=max_p95_ms,
        detail=f"n={len(samples_ms)} p95={p95:.2f}ms",
    )

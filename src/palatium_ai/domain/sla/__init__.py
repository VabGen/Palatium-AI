# src/palatium_ai/domain/sla/__init__.py

"""SLA gate contracts (success rate, latency percentiles)."""

from palatium_ai.domain.sla.corpus import build_benchmark_corpus
from palatium_ai.domain.sla.gates import (
    SlaGateResult,
    evaluate_p95_latency_ms,
    evaluate_success_rate,
    percentile,
)

__all__ = [
    "SlaGateResult",
    "build_benchmark_corpus",
    "evaluate_p95_latency_ms",
    "evaluate_success_rate",
    "percentile",
]

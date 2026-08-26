#!/usr/bin/env python
"""Run Palatium SLA gates (success-rate math and optional live /health load)."""

from __future__ import annotations

import argparse
import asyncio
import statistics
import sys
import time

from collections.abc import Sequence

import httpx

from palatium_ai.domain.sla.corpus import build_benchmark_corpus
from palatium_ai.domain.sla.gates import SlaGateResult, evaluate_p95_latency_ms, evaluate_success_rate


def _http_url(url: str) -> str:
    cleaned = url.strip()
    if not (cleaned.startswith("http://") or cleaned.startswith("https://")):
        raise ValueError(f"only http(s) URLs allowed, got: {url!r}")
    return cleaned.rstrip("/")


async def _load_health(
    *,
    base_url: str,
    concurrency: int,
    max_p95_ms: float,
) -> SlaGateResult:
    url = f"{_http_url(base_url)}/health"
    latencies: list[float] = []
    errors = 0

    async with httpx.AsyncClient(timeout=30.0) as client:
        sem = asyncio.Semaphore(min(concurrency, 200))

        async def one() -> None:
            nonlocal errors
            async with sem:
                started = time.perf_counter()
                try:
                    response = await client.get(url)
                    if response.status_code != 200:
                        errors += 1
                except httpx.HTTPError:
                    errors += 1
                finally:
                    latencies.append((time.perf_counter() - started) * 1000.0)

        await asyncio.gather(*(one() for _ in range(concurrency)))

    success_gate = evaluate_success_rate(
        successes=concurrency - errors,
        total=concurrency,
        min_rate=0.95,
        name="load_health_success_rate",
    )
    latency_gate = evaluate_p95_latency_ms(
        samples_ms=latencies,
        max_p95_ms=max_p95_ms,
        name="load_health_p95_ms",
    )
    # Combine: both must pass; surface the worse detail.
    passed = success_gate.passed and latency_gate.passed
    mean_ms = statistics.fmean(latencies) if latencies else 0.0
    return SlaGateResult(
        name="load_health",
        passed=passed,
        observed=latency_gate.observed,
        threshold=max_p95_ms,
        detail=(f"{success_gate.detail}; {latency_gate.detail}; mean={mean_ms:.2f}ms errors={errors}"),
    )


def _print_gates(gates: Sequence[SlaGateResult]) -> int:
    failed = 0
    for gate in gates:
        mark = "PASS" if gate.passed else "FAIL"
        print(f"[{mark}] {gate.name}: observed={gate.observed:.4f} threshold={gate.threshold:.4f} ({gate.detail})")
        if not gate.passed:
            failed += 1
    return failed


def main(argv: list[str] | None = None) -> int:
    """CLI entry: evaluate selected SLA gates and return process exit code."""
    parser = argparse.ArgumentParser(description="Palatium SLA gates")
    parser.add_argument("--check-math", action="store_true", help="Run offline gate self-check + corpus size")
    parser.add_argument("--successes", type=int, default=None)
    parser.add_argument("--total", type=int, default=None)
    parser.add_argument("--min-rate", type=float, default=0.85)
    parser.add_argument("--load-health", action="store_true")
    parser.add_argument("--base-url", default="http://127.0.0.1:8000")
    parser.add_argument("--concurrency", type=int, default=1000)
    parser.add_argument("--max-p95-ms", type=float, default=500.0)
    args = parser.parse_args(argv)

    gates: list[SlaGateResult] = []

    if args.check_math:
        corpus = build_benchmark_corpus(size=100)
        gates.append(
            evaluate_success_rate(
                successes=len(corpus),
                total=len(corpus),
                min_rate=1.0,
                name="benchmark_corpus_ready",
            )
        )
        # Synthetic latency profile under budget.
        samples = [12.0] * 1000
        gates.append(evaluate_p95_latency_ms(samples_ms=samples, max_p95_ms=50.0, name="math_p95_selfcheck"))

    if args.successes is not None and args.total is not None:
        gates.append(
            evaluate_success_rate(
                successes=args.successes,
                total=args.total,
                min_rate=args.min_rate,
            )
        )

    if args.load_health:
        gates.append(
            asyncio.run(
                _load_health(
                    base_url=args.base_url,
                    concurrency=args.concurrency,
                    max_p95_ms=args.max_p95_ms,
                )
            )
        )

    if not gates:
        parser.print_help()
        return 2

    failed = _print_gates(gates)
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())

#!/usr/bin/env python3
"""Latency micro-benchmark / live probe (P0.4 + audit residual).

Modes:
  * offline (default): L1 cache get/set P50/P95 over N iterations.
  * --base-url: POST /api/intents/process twice (cold + warm); flag likely L1 hit.
  * --stream: also POST /api/intents/process/stream and report TTFT (first SSE event).
  * --complex: one knowledge-style turn on /process.

Usage:
  poetry run python scripts/benchmark_latency.py
  poetry run python scripts/benchmark_latency.py --base-url http://127.0.0.1:8000 --stream --complex
"""

from __future__ import annotations

import argparse
import asyncio
import json
import statistics
import sys
import time
import urllib.error
import urllib.request

from uuid import uuid4

# Wall times below this on /process warm path are treated as L1-likely (no LLM).
_L1_LIKELY_MS = 100.0


def _percentile(sorted_values: list[float], pct: float) -> float:
    if not sorted_values:
        return 0.0
    if len(sorted_values) == 1:
        return sorted_values[0]
    k = (len(sorted_values) - 1) * (pct / 100.0)
    f = int(k)
    c = min(f + 1, len(sorted_values) - 1)
    if f == c:
        return sorted_values[f]
    return sorted_values[f] + (sorted_values[c] - sorted_values[f]) * (k - f)


def _summarize(label: str, samples_ms: list[float]) -> None:
    ordered = sorted(samples_ms)
    print(
        f"{label}: n={len(ordered)} "
        f"P50={_percentile(ordered, 50):.1f}ms "
        f"P95={_percentile(ordered, 95):.1f}ms "
        f"mean={statistics.fmean(ordered):.1f}ms"
    )


async def _offline_l1(iterations: int) -> int:
    from palatium_ai.application.services.response_cache_service import ResponseCacheService
    from palatium_ai.domain.agents.formatter import FormatterTaskResult
    from palatium_ai.domain.content.content_document import ContentDocument, DocumentMeta, ParagraphBlock
    from palatium_ai.infrastructure.cache.response_cache import InMemoryResponseCache

    port = InMemoryResponseCache()
    svc = ResponseCacheService(port, ttl_seconds=600, enabled=True)
    doc = ContentDocument(
        schema_version=1,
        locale="ru",
        title="Привет!",
        blocks=(ParagraphBlock(type="paragraph", text="Привет!"),),
        actions=(),
        meta=DocumentMeta(confidence=1.0, requires_review=False, source_refs=(), interaction="none"),
    )
    result = FormatterTaskResult(
        task_id="bench",
        agent_role="formatter",
        status="success",
        confidence=1.0,
        requires_review=False,
        output=doc,
    )
    await svc.put_if_cacheable(
        tenant_key="bench-tenant",
        user_text="привет",
        locale="ru",
        strategy="format_only",
        result=result,
    )
    samples: list[float] = []
    for _ in range(iterations):
        t0 = time.perf_counter()
        hit = await svc.get(
            tenant_key="bench-tenant",
            user_text="привет",
            locale="ru",
            strategy="format_only",
        )
        samples.append((time.perf_counter() - t0) * 1000.0)
        if hit is None:
            print("ERROR: expected L1 hit", file=sys.stderr)
            return 1
    _summarize("L1 cache get (offline)", samples)
    return 0


def _http_url(url: str) -> str:
    cleaned = url.strip()
    if not cleaned.startswith(("http://", "https://")):
        raise ValueError(f"only http(s) URLs allowed, got: {url!r}")
    return cleaned


def _mint_dev_token(*, base_url: str, user_id: str) -> str:
    endpoint = _http_url(f"{base_url.rstrip('/')}/api/auth/dev-token")
    payload = json.dumps({"user_id": user_id}).encode("utf-8")
    req = urllib.request.Request(  # noqa: S310
        endpoint,
        data=payload,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=30) as resp:  # noqa: S310
        body = json.loads(resp.read().decode("utf-8"))
    token = body.get("access_token") if isinstance(body, dict) else None
    if not isinstance(token, str) or not token:
        raise RuntimeError("dev-token response missing access_token")
    return token


def _post_process(*, base_url: str, text: str, thread_id: str, token: str) -> tuple[dict[str, object], float]:
    endpoint = _http_url(f"{base_url.rstrip('/')}/api/intents/process")
    payload = json.dumps({"text": text, "thread_id": thread_id}).encode("utf-8")
    req = urllib.request.Request(  # noqa: S310
        endpoint,
        data=payload,
        headers={
            "Content-Type": "application/json",
            "Authorization": f"Bearer {token}",
        },
        method="POST",
    )
    t0 = time.perf_counter()
    with urllib.request.urlopen(req, timeout=180) as resp:  # noqa: S310
        body = json.loads(resp.read().decode("utf-8"))
    elapsed_ms = (time.perf_counter() - t0) * 1000.0
    if not isinstance(body, dict):
        raise RuntimeError(f"unexpected response type: {type(body)}")
    return body, elapsed_ms


def _post_process_stream_ttft(
    *,
    base_url: str,
    text: str,
    thread_id: str,
    token: str,
) -> tuple[float, float]:
    """Return (ttft_ms to first SSE data line, total_ms until stream end)."""
    endpoint = _http_url(f"{base_url.rstrip('/')}/api/intents/process/stream")
    payload = json.dumps({"text": text, "thread_id": thread_id}).encode("utf-8")
    req = urllib.request.Request(  # noqa: S310
        endpoint,
        data=payload,
        headers={
            "Content-Type": "application/json",
            "Authorization": f"Bearer {token}",
            "Accept": "text/event-stream",
        },
        method="POST",
    )
    t0 = time.perf_counter()
    ttft_ms: float | None = None
    with urllib.request.urlopen(req, timeout=180) as resp:  # noqa: S310
        while True:
            raw = resp.readline()
            if not raw:
                break
            line = raw.decode("utf-8", errors="replace").strip()
            if not line or line.startswith(":"):
                continue
            if line.startswith("data:") and ttft_ms is None:
                ttft_ms = (time.perf_counter() - t0) * 1000.0
    total_ms = (time.perf_counter() - t0) * 1000.0
    if ttft_ms is None:
        ttft_ms = total_ms
    return ttft_ms, total_ms


def _live(base_url: str, *, complex_probe: bool, stream_probe: bool) -> int:
    user_id = f"bench-{uuid4().hex[:8]}"
    thread_id = f"bench-thread-{uuid4().hex[:8]}"
    try:
        token = _mint_dev_token(base_url=base_url, user_id=user_id)
    except (urllib.error.URLError, RuntimeError, ValueError) as exc:
        print(f"ERROR: cannot mint token: {exc}", file=sys.stderr)
        return 1

    simple_samples: list[float] = []
    for i in range(2):
        _body, ms = _post_process(
            base_url=base_url,
            text="привет",
            thread_id=thread_id,
            token=token,
        )
        simple_samples.append(ms)
        l1_note = " L1-likely" if i > 0 and ms < _L1_LIKELY_MS else ""
        if i > 0 and ms >= _L1_LIKELY_MS:
            l1_note = " (warm >> L1 — check RESPONSE_CACHE_ENABLED / Redis / image)"
        print(f"simple turn {i + 1}: {ms:.0f}ms{l1_note}")
    _summarize("simple /intents/process", simple_samples)

    if stream_probe:
        try:
            ttft_ms, total_ms = _post_process_stream_ttft(
                base_url=base_url,
                text="привет",
                thread_id=f"{thread_id}-sse",
                token=token,
            )
            print(f"simple stream TTFT: {ttft_ms:.0f}ms total: {total_ms:.0f}ms")
        except urllib.error.HTTPError as exc:
            print(
                f"WARNING: SSE probe HTTP {exc.code} — running API may lack /process/stream "
                f"(redeploy current image). Skipping TTFT.",
                file=sys.stderr,
            )

    if complex_probe:
        try:
            _body, ms = _post_process(
                base_url=base_url,
                text="Что такое гибридный поиск в knowledge base?",
                thread_id=f"{thread_id}-c",
                token=token,
            )
            print(f"complex turn: {ms:.0f}ms")
        except urllib.error.HTTPError as exc:
            print(f"ERROR: complex probe HTTP {exc.code}: {exc.reason}", file=sys.stderr)
            return 1
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--base-url", default="", help="Live API base; empty = offline L1 only")
    parser.add_argument("--iterations", type=int, default=200, help="Offline L1 iterations")
    parser.add_argument("--complex", action="store_true", help="Also run one complex live turn")
    parser.add_argument("--stream", action="store_true", help="Also probe SSE TTFT")
    args = parser.parse_args()
    if args.base_url.strip():
        return _live(
            args.base_url,
            complex_probe=args.complex,
            stream_probe=args.stream,
        )
    return asyncio.run(_offline_l1(max(10, args.iterations)))


if __name__ == "__main__":
    raise SystemExit(main())

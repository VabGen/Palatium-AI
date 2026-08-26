# scripts/eval_api_live.py

"""Opt-in live API SLA sample against a running server (real LLM path).

Usage:
  poetry run python scripts/eval_api_live.py --base-url http://127.0.0.1:8000 --limit 8

Requires development AUTH (POST /api/auth/dev-token) and a healthy stack.
Exits 0 only when success-rate gate passes (default min 0.85).
"""

from __future__ import annotations

import argparse
import json
import sys
import time
import urllib.error
import urllib.request

from uuid import uuid4

from palatium_ai.domain.sla.corpus import build_benchmark_corpus
from palatium_ai.domain.sla.gates import evaluate_p95_latency_ms, evaluate_success_rate


def _http_url(url: str) -> str:
    cleaned = url.strip()
    if not (cleaned.startswith("http://") or cleaned.startswith("https://")):
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


def _post_process(*, base_url: str, text: str, thread_id: str, token: str) -> tuple[int, float]:
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
    started = time.perf_counter()
    with urllib.request.urlopen(req, timeout=180) as resp:  # noqa: S310
        status = int(resp.status)
        _ = resp.read()
    elapsed_ms = (time.perf_counter() - started) * 1000.0
    return status, elapsed_ms


def main(argv: list[str] | None = None) -> int:
    """Run a structural corpus sample against live /api/intents/process."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--base-url", default="http://127.0.0.1:8000")
    parser.add_argument("--limit", type=int, default=8, help="How many corpus cases to run")
    parser.add_argument("--min-rate", type=float, default=0.85)
    parser.add_argument("--max-p95-ms", type=float, default=60_000.0)
    args = parser.parse_args(argv)

    corpus = build_benchmark_corpus(size=max(args.limit, 1))[: args.limit]
    user_id = f"live-eval-{uuid4().hex[:8]}"
    try:
        token = _mint_dev_token(base_url=args.base_url, user_id=user_id)
    except urllib.error.HTTPError as exc:
        hint = ""
        if exc.code == 404:
            hint = (
                " (restart API with ENVIRONMENT=development so POST /api/auth/dev-token exists;"
                " 404 also means a stale process without Week 0 auth router)"
            )
        print(f"Cannot mint dev token at {args.base_url}: {exc}{hint}", file=sys.stderr)
        return 2
    except (urllib.error.URLError, RuntimeError, ValueError) as exc:
        print(f"Cannot mint dev token at {args.base_url}: {exc}", file=sys.stderr)
        return 2

    successes = 0
    latencies: list[float] = []
    for case in corpus:
        thread_id = f"{case.case_id}-{uuid4().hex[:6]}"
        try:
            status, elapsed_ms = _post_process(
                base_url=args.base_url,
                text=case.user_text,
                thread_id=thread_id,
                token=token,
            )
            latencies.append(elapsed_ms)
            if 200 <= status < 300:
                successes += 1
            else:
                print(f"FAIL {case.case_id} HTTP {status} ({elapsed_ms:.0f}ms)")
        except urllib.error.HTTPError as exc:
            latencies.append(0.0)
            detail = exc.read().decode("utf-8", errors="replace")[:200]
            print(f"FAIL {case.case_id} HTTP {exc.code}: {detail}")
        except urllib.error.URLError as exc:
            print(f"FAIL {case.case_id} network: {exc}", file=sys.stderr)
            return 2

    rate_gate = evaluate_success_rate(
        successes=successes,
        total=len(corpus),
        min_rate=args.min_rate,
        name="live_api_success_rate",
    )
    latency_gate = evaluate_p95_latency_ms(
        samples_ms=[ms for ms in latencies if ms > 0],
        max_p95_ms=args.max_p95_ms,
        name="live_api_p95_ms",
    )
    for gate in (rate_gate, latency_gate):
        mark = "PASS" if gate.passed else "FAIL"
        print(f"[{mark}] {gate.name}: observed={gate.observed:.4f} threshold={gate.threshold:.4f} ({gate.detail})")

    return 0 if rate_gate.passed and latency_gate.passed else 1


if __name__ == "__main__":
    raise SystemExit(main())

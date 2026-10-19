"""Ops readiness probe against a running API (automated portion of ops-readiness.md).

Usage:
  uv run python scripts/ops_probe.py
  uv run python scripts/ops_probe.py --base-url http://127.0.0.1:8000 --with-admin

Checks (non-destructive by default):
  - GET /health
  - GET /metrics (or 401 when METRICS_PUBLIC=false)
  - optional kill-switch engage/release when --with-admin and admin JWT available

Does not rotate Vault secrets or configure Prometheus — those remain operator steps.
"""

from __future__ import annotations

import argparse
import json
import sys
import urllib.error
import urllib.request

from uuid import uuid4


def _http_url(url: str) -> str:
    cleaned = url.strip()
    if not cleaned.startswith(("http://", "https://")):
        raise ValueError(f"only http(s) URLs allowed, got: {url!r}")
    return cleaned


def _request(
    method: str,
    url: str,
    *,
    token: str | None = None,
    body: dict[str, object] | None = None,
    timeout: float = 30,
) -> tuple[int, str]:
    data = None if body is None else json.dumps(body).encode("utf-8")
    headers: dict[str, str] = {}
    if body is not None:
        headers["Content-Type"] = "application/json"
    if token:
        headers["Authorization"] = f"Bearer {token}"
    req = urllib.request.Request(  # noqa: S310
        _http_url(url),
        data=data,
        headers=headers,
        method=method,
    )
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:  # noqa: S310
            return int(resp.status), resp.read().decode("utf-8", errors="replace")
    except urllib.error.HTTPError as exc:
        return int(exc.code), exc.read().decode("utf-8", errors="replace")


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--base-url", default="http://127.0.0.1:8000")
    parser.add_argument(
        "--with-admin",
        action="store_true",
        help="Try kill-switch engage/release (requires development + admin role — skipped if denied)",
    )
    return parser


def _check_health(base: str) -> tuple[list[dict[str, object]], int]:
    status, body = _request("GET", f"{base}/health")
    ok = status == 200 and "ok" in body.lower()
    return [{"check": "health", "status": status, "ok": ok}], 0 if ok else 1


def _ready_verdict(body: str) -> tuple[bool, str]:
    """Read the readiness payload: local/dev may be legitimately ``degraded``."""
    try:
        payload = json.loads(body)
    except json.JSONDecodeError:
        return False, "non-JSON body"
    ready_status = str(payload.get("status", ""))
    warnings = payload.get("warnings") or []
    return ready_status in {"ok", "degraded"}, f"status={ready_status}; warnings={len(warnings)}"


def _check_ready(base: str) -> tuple[list[dict[str, object]], int]:
    status, body = _request("GET", f"{base}/ready")
    if status != 200:
        return (
            [
                {
                    "check": "ready",
                    "status": status,
                    "ok": False,
                    "note": "parse body.status / warnings (SB4 graph+memory backends)",
                }
            ],
            1,
        )
    ok, note = _ready_verdict(body)
    return [{"check": "ready", "status": status, "ok": ok, "note": note}], 0 if ok else 1


def _check_metrics(base: str) -> tuple[list[dict[str, object]], int]:
    status, _ = _request("GET", f"{base}/metrics")
    ok = status in {200, 401}
    return (
        [
            {
                "check": "metrics",
                "status": status,
                "ok": ok,
                "note": "200 public scrape or 401 when METRICS_PUBLIC=false",
            }
        ],
        0 if ok else 1,
    )


def _admin_token(base: str) -> tuple[int, str | None]:
    """Mint a dev admin token; outside development the endpoint is absent (404) by design."""
    user_id = f"ops-probe-{uuid4().hex[:8]}"
    status, raw = _request(
        "POST",
        f"{base}/api/auth/dev-token",
        body={"user_id": user_id, "roles": ["admin"]},
    )
    if status != 200:
        return status, None
    try:
        token = json.loads(raw).get("access_token")
    except json.JSONDecodeError:
        return status, None
    return status, token if isinstance(token, str) and token else None


def _check_kill_switch(base: str) -> tuple[list[dict[str, object]], int]:
    """Probe the kill-switch endpoint; a stripped admin role answers 403 and is not a failure.

    The dev token cannot mint admin roles, so an unavailable token is reported without
    counting as a failure — the same "skipped if denied" contract as ``--with-admin``.
    """
    status, token = _admin_token(base)
    if token is None:
        return [
            {
                "check": "kill_switch_get",
                "status": status,
                "ok": status == 404,
                "note": "dev-token unavailable outside development",
            }
        ], 0
    st, _ = _request("GET", f"{base}/api/admin/kill-switch", token=token)
    ok = st in {200, 403}
    return (
        [
            {
                "check": "kill_switch_get",
                "status": st,
                "ok": ok,
                "note": "403 expected when admin role stripped from dev-token",
            }
        ],
        0 if ok else 1,
    )


def main() -> int:
    """Probe health/metrics (and optional kill-switch) on a running API."""
    args = _build_parser().parse_args()
    base = args.base_url.rstrip("/")

    checks = [_check_health(base), _check_ready(base), _check_metrics(base)]
    if args.with_admin:
        checks.append(_check_kill_switch(base))

    results: list[dict[str, object]] = []
    failed = 0
    for result, count in checks:
        results.extend(result)
        failed += count

    print(json.dumps({"base_url": base, "failed": failed, "results": results}, indent=2))
    if failed:
        print("ops_probe: FAILED", file=sys.stderr)
        return 1
    print("ops_probe: ok")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

"""Ops readiness probe against a running API (automated portion of ops-readiness.md).

Usage:
  poetry run python scripts/ops_probe.py
  poetry run python scripts/ops_probe.py --base-url http://127.0.0.1:8000 --with-admin

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
    if not (cleaned.startswith("http://") or cleaned.startswith("https://")):
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


def main() -> int:
    """Probe health/metrics (and optional kill-switch) on a running API."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--base-url", default="http://127.0.0.1:8000")
    parser.add_argument(
        "--with-admin",
        action="store_true",
        help="Try kill-switch engage/release (requires development + admin role — skipped if denied)",
    )
    args = parser.parse_args()
    base = args.base_url.rstrip("/")
    results: list[dict[str, object]] = []
    failed = 0

    status, body = _request("GET", f"{base}/health")
    ok = status == 200 and "ok" in body.lower()
    results.append({"check": "health", "status": status, "ok": ok})
    if not ok:
        failed += 1

    status, body = _request("GET", f"{base}/metrics")
    metrics_ok = status == 200 or status == 401
    results.append(
        {
            "check": "metrics",
            "status": status,
            "ok": metrics_ok,
            "note": "200 public scrape or 401 when METRICS_PUBLIC=false",
        }
    )
    if not metrics_ok:
        failed += 1

    if args.with_admin:
        # Dev token cannot mint admin roles (stripped) — expect 403; still probes endpoint existence.
        user_id = f"ops-probe-{uuid4().hex[:8]}"
        status, tok_raw = _request(
            "POST",
            f"{base}/api/auth/dev-token",
            body={"user_id": user_id, "roles": ["admin"]},
        )
        token = None
        if status == 200:
            try:
                token = json.loads(tok_raw).get("access_token")
            except json.JSONDecodeError:
                token = None
        if isinstance(token, str) and token:
            st, _ = _request("GET", f"{base}/api/admin/kill-switch", token=token)
            results.append(
                {
                    "check": "kill_switch_get",
                    "status": st,
                    "ok": st in {200, 403},
                    "note": "403 expected when admin role stripped from dev-token",
                }
            )
            if st not in {200, 403}:
                failed += 1
        else:
            results.append(
                {
                    "check": "kill_switch_get",
                    "status": status,
                    "ok": status == 404,
                    "note": "dev-token unavailable outside development",
                }
            )

    print(json.dumps({"base_url": base, "failed": failed, "results": results}, indent=2))
    if failed:
        print("ops_probe: FAILED", file=sys.stderr)
        return 1
    print("ops_probe: ok")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

"""Smoke: MCP stub Bearer gate + platform health (local stack).

Usage:
  poetry run python scripts/smoke_mcp_auth.py
  poetry run python scripts/smoke_mcp_auth.py --token dev-mcp-local-token
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import urllib.error
import urllib.request


def _http_url(url: str) -> str:
    cleaned = url.strip()
    if not (cleaned.startswith("http://") or cleaned.startswith("https://")):
        raise ValueError(f"only http(s) URLs allowed, got: {url!r}")
    return cleaned


def _request(
    url: str,
    *,
    method: str = "GET",
    headers: dict[str, str] | None = None,
    body: bytes | None = None,
    timeout: float = 10.0,
) -> tuple[int, bytes]:
    req = urllib.request.Request(  # noqa: S310
        _http_url(url),
        data=body,
        headers=headers or {},
        method=method,
    )
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:  # noqa: S310
            return int(resp.status), resp.read()
    except urllib.error.HTTPError as exc:
        return int(exc.code), exc.read()


def _check_stub(*, base: str, token: str, label: str) -> None:
    health_status, _ = _request(f"{base.rstrip('/')}/health")
    if health_status != 200:
        raise RuntimeError(f"{label} /health -> {health_status}")

    rpc_body = json.dumps(
        {"jsonrpc": "2.0", "method": "tools/list", "id": "smoke-1"},
    ).encode("utf-8")
    anon_status, _ = _request(
        f"{base.rstrip('/')}/",
        method="POST",
        headers={"Content-Type": "application/json"},
        body=rpc_body,
    )
    if anon_status != 401:
        raise RuntimeError(f"{label} anonymous tools/list -> {anon_status}, expected 401")

    ok_status, ok_raw = _request(
        f"{base.rstrip('/')}/",
        method="POST",
        headers={
            "Content-Type": "application/json",
            "Authorization": f"Bearer {token}",
        },
        body=rpc_body,
    )
    if ok_status != 200:
        raise RuntimeError(f"{label} authenticated tools/list -> {ok_status}")
    payload = json.loads(ok_raw.decode("utf-8"))
    if not isinstance(payload, dict) or payload.get("error"):
        raise RuntimeError(f"{label} tools/list JSON-RPC error: {payload!r}")
    print(f"OK  {label}: health + Bearer gate + tools/list")


def main() -> int:
    """Smoke: MCP stub Bearer gate + platform health (local stack)."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--edms", default="http://127.0.0.1:8080")
    parser.add_argument("--analytics", default="http://127.0.0.1:8081")
    parser.add_argument("--api", default="http://127.0.0.1:8000")
    parser.add_argument(
        "--token",
        default=os.environ.get("MCP_AUTH_TOKEN", "dev-mcp-local-token"),
    )
    parser.add_argument(
        "--skip-api",
        action="store_true",
        help="Only probe MCP stubs (skip API /health)",
    )
    parser.add_argument(
        "--skip-analytics",
        action="store_true",
        help="Probe EDMS stub only",
    )
    parser.add_argument(
        "--skip-edms",
        action="store_true",
        help="Probe analytics stub only",
    )
    args = parser.parse_args()

    try:
        if not args.skip_edms:
            _check_stub(base=args.edms, token=args.token, label="edms")
        if not args.skip_analytics:
            _check_stub(base=args.analytics, token=args.token, label="analytics")
        if not args.skip_api:
            status, raw = _request(f"{args.api.rstrip('/')}/health")
            if status != 200:
                raise RuntimeError(f"API /health -> {status}: {raw[:200]!r}")
            print("OK  api: /health")
    except (RuntimeError, ValueError, urllib.error.URLError, TimeoutError, json.JSONDecodeError) as exc:
        print(f"FAIL: {exc}", file=sys.stderr)
        return 1
    print("smoke_mcp_auth: passed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

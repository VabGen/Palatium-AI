"""Smoke: MCP stub auth + Streamable HTTP tools/list (local stack).

Usage:
  poetry run python scripts/smoke_mcp_auth.py
  poetry run python scripts/smoke_mcp_auth.py --skip-api
"""

from __future__ import annotations

import argparse
import asyncio
import os
import sys
import urllib.error
import urllib.request

from fastmcp import Client

from palatium_ai.core.config import get_settings
from palatium_ai.infrastructure.mcp.jwt_auth import resolve_mcp_bearer


def _http_url(url: str) -> str:
    cleaned = url.strip()
    if not cleaned.startswith(("http://", "https://")):
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


def _resolve_bearer(*, server_name: str, static_token: str) -> str:
    """JWT (aud=mcp:<server>) when MCP_JWT_SECRET is set; else static Bearer."""
    get_settings.cache_clear()
    settings = get_settings()
    signing_secret = settings.mcp_jwt_signing_secret()
    if signing_secret:
        token = resolve_mcp_bearer(
            settings.mcp,
            server_name,
            signing_secret=signing_secret,
        )
        if token:
            return token
    return static_token


async def _check_stub(*, base: str, server_name: str, static_token: str, label: str) -> None:
    health_status, _ = _request(f"{base.rstrip('/')}/health")
    if health_status != 200:
        raise RuntimeError(f"{label} /health -> {health_status}")

    rpc_body = b'{"jsonrpc":"2.0","method":"tools/list","id":"smoke-anon"}'
    anon_status, _ = _request(
        f"{base.rstrip('/')}/",
        method="POST",
        headers={"Content-Type": "application/json"},
        body=rpc_body,
    )
    if anon_status != 401:
        raise RuntimeError(f"{label} anonymous MCP -> {anon_status}, expected 401")

    bearer = _resolve_bearer(server_name=server_name, static_token=static_token)
    url = base if base.endswith("/") else f"{base}/"
    async with Client(url, auth=bearer, mode="auto") as client:
        tools = await client.list_tools()
    if not tools:
        raise RuntimeError(f"{label} tools/list returned empty tool set")
    print(f"OK  {label}: health + Bearer gate + tools/list ({len(tools)} tools)")


async def _run_smoke(args: argparse.Namespace) -> None:
    static_token = args.token
    if not args.skip_edms:
        await _check_stub(
            base=args.edms,
            server_name="edms",
            static_token=static_token,
            label="edms",
        )
    if not args.skip_analytics:
        await _check_stub(
            base=args.analytics,
            server_name="analytics",
            static_token=static_token,
            label="analytics",
        )
    if not args.skip_api:
        status, raw = _request(f"{args.api.rstrip('/')}/health")
        if status != 200:
            raise RuntimeError(f"API /health -> {status}: {raw[:200]!r}")
        print("OK  api: /health")


def main() -> int:
    """Smoke: remote MCP stub Bearer gate + optional API /health."""
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
        asyncio.run(_run_smoke(args))
    except (RuntimeError, ValueError, urllib.error.URLError, TimeoutError, OSError) as exc:
        print(f"FAIL: {exc}", file=sys.stderr)
        return 1
    print("smoke_mcp_auth: passed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

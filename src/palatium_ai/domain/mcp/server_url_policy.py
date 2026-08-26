# src/palatium_ai/domain/mcp/server_url_policy.py

"""Allowlist MCP registry URLs (SSRF / spoofing gate)."""

from __future__ import annotations

import ipaddress

from collections.abc import Collection
from urllib.parse import ParseResult, urlparse


class UnsafeMcpServerUrlError(ValueError):
    """Raised when an MCP server URL is rejected by platform policy."""


_BLOCKED_HOSTNAMES: frozenset[str] = frozenset(
    {
        "metadata.google.internal",
        "metadata",
        "metadata.aws.internal",
    }
)

_DEFAULT_HTTP_HOSTS: frozenset[str] = frozenset(
    {
        "localhost",
        "127.0.0.1",
        "::1",
        "mcp-edms",
        "mcp-analytics",
    }
)

_LOOPBACK_HOSTS: frozenset[str] = frozenset({"localhost", "127.0.0.1", "::1"})


def assert_mcp_server_url_safe(
    url: str,
    *,
    allow_http_loopback: bool = True,
    http_allowed_hosts: Collection[str] | None = None,
) -> str:
    """Validate and normalize an MCP base URL.

    Rules:
    - ``https`` allowed for non-blocked hosts (incl. RFC1918 for enterprise MCP).
    - ``http`` only when hostname is in ``http_allowed_hosts`` (local stubs / compose DNS).
    - Link-local / metadata / unspecified / multicast IPs always denied.
    """
    stripped = url.strip()
    if not stripped:
        raise UnsafeMcpServerUrlError("MCP server URL is empty")

    try:
        parsed = urlparse(stripped)
    except ValueError as exc:
        raise UnsafeMcpServerUrlError("MCP server URL is malformed") from exc

    host = _require_safe_host(parsed)
    http_hosts = _resolve_http_hosts(
        allow_http_loopback=allow_http_loopback,
        http_allowed_hosts=http_allowed_hosts,
    )
    _assert_http_host_allowed(
        scheme=(parsed.scheme or "").lower(),
        host=host,
        http_hosts=http_hosts,
        allow_http_loopback=allow_http_loopback,
    )
    return stripped


def filter_mcp_server_map(
    servers: dict[str, str],
    *,
    allow_http_loopback: bool = True,
    http_allowed_hosts: Collection[str] | None = None,
) -> tuple[dict[str, str], list[tuple[str, str]]]:
    """Return accepted servers and a list of (name, reason) for rejected entries."""
    accepted: dict[str, str] = {}
    rejected: list[tuple[str, str]] = []
    for name, url in servers.items():
        key = str(name).strip()
        if not key:
            rejected.append(("", "empty server name"))
            continue
        try:
            accepted[key] = assert_mcp_server_url_safe(
                str(url),
                allow_http_loopback=allow_http_loopback,
                http_allowed_hosts=http_allowed_hosts,
            )
        except UnsafeMcpServerUrlError as exc:
            rejected.append((key, str(exc)))
    return accepted, rejected


def _require_safe_host(parsed: ParseResult) -> str:
    scheme = (parsed.scheme or "").lower()
    host = (parsed.hostname or "").strip().lower().rstrip(".")
    if scheme not in {"http", "https"}:
        raise UnsafeMcpServerUrlError(f"Denied MCP URL scheme {scheme!r}")
    if not host:
        raise UnsafeMcpServerUrlError("MCP server URL must include a hostname")
    if parsed.username or parsed.password:
        raise UnsafeMcpServerUrlError("MCP server URL must not embed credentials")
    if host in _BLOCKED_HOSTNAMES:
        raise UnsafeMcpServerUrlError(f"Denied MCP host {host!r}")
    _assert_ip_not_ssrf_pivot(host)
    return host


def _assert_ip_not_ssrf_pivot(host: str) -> None:
    try:
        addr = ipaddress.ip_address(host)
    except ValueError:
        return
    if addr.is_link_local or addr.is_unspecified or addr.is_multicast:
        raise UnsafeMcpServerUrlError(f"Denied non-routable MCP IP {host!r}")
    if addr in ipaddress.ip_network("169.254.0.0/16"):
        raise UnsafeMcpServerUrlError(f"Denied metadata MCP IP {host!r}")


def _resolve_http_hosts(
    *,
    allow_http_loopback: bool,
    http_allowed_hosts: Collection[str] | None,
) -> frozenset[str]:
    if not allow_http_loopback:
        return frozenset()
    if http_allowed_hosts is None:
        return _DEFAULT_HTTP_HOSTS
    return frozenset(h.strip().lower() for h in http_allowed_hosts if str(h).strip())


def _assert_http_host_allowed(
    *,
    scheme: str,
    host: str,
    http_hosts: frozenset[str],
    allow_http_loopback: bool,
) -> None:
    if scheme != "http":
        return
    is_loopback = host in _LOOPBACK_HOSTS or _host_is_loopback_ip(host)
    if host in http_hosts or (allow_http_loopback and is_loopback):
        return
    raise UnsafeMcpServerUrlError(
        f"HTTP MCP host {host!r} is not in MCP_HTTP_ALLOWED_HOSTS",
    )


def _host_is_loopback_ip(host: str) -> bool:
    try:
        return ipaddress.ip_address(host).is_loopback
    except ValueError:
        return False

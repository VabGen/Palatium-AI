# mcp_servers/gateway/upstream_policy.py

"""SSRF allowlist for the MCP gateway upstream URL (020).

The gateway runs in its own container and is configured by an operator via
``MCP_UPSTREAM_URL``. A mistyped or hostile value (cloud metadata IP, ``file://``,
embedded credentials) must fail closed at startup — the gateway is a proxy and
will happily forward whatever it is pointed at.

Standalone copy of the platform policy (``domain/mcp/server_url_policy.py``): the
stub/gateway image does not ship the ``palatium_ai`` application package.
"""

from __future__ import annotations

import ipaddress
import os

from collections.abc import Collection
from urllib.parse import ParseResult, urlparse

_DEFAULT_HTTP_HOSTS: frozenset[str] = frozenset(
    {
        "localhost",
        "127.0.0.1",
        "::1",
        "edms",
        "analytics",
        "mcp-edms",
        "mcp-analytics",
    }
)

_BLOCKED_HOSTNAMES: frozenset[str] = frozenset(
    {
        "metadata.google.internal",
        "metadata",
        "metadata.aws.internal",
    }
)

_LOOPBACK_HOSTS: frozenset[str] = frozenset({"localhost", "127.0.0.1", "::1"})


class UnsafeUpstreamUrlError(ValueError):
    """Raised when ``MCP_UPSTREAM_URL`` is rejected by gateway policy."""


def assert_upstream_url_safe(
    url: str,
    *,
    http_allowed_hosts: Collection[str] | None = None,
) -> str:
    """Validate and normalize the gateway upstream MCP URL.

    Rules:
    - ``https`` allowed for non-blocked hosts (incl. RFC1918 for enterprise MCP).
    - ``http`` only when the hostname is an allowlisted loopback / compose DNS name.
    - Link-local / metadata / unspecified / multicast IPs and embedded credentials always denied.
    """
    stripped = url.strip()
    if not stripped:
        raise UnsafeUpstreamUrlError("MCP_UPSTREAM_URL is empty")

    try:
        parsed = urlparse(stripped)
    except ValueError as exc:
        raise UnsafeUpstreamUrlError("MCP_UPSTREAM_URL is malformed") from exc

    host = _require_safe_host(parsed)
    http_hosts = _resolve_http_hosts(http_allowed_hosts)
    if (parsed.scheme or "").lower() == "http" and not _http_host_allowed(host, http_hosts):
        raise UnsafeUpstreamUrlError(
            f"HTTP upstream host {host!r} is not in MCP_UPSTREAM_HTTP_ALLOWED_HOSTS",
        )
    return stripped


def assert_env_upstream_url_safe(url: str) -> str:
    """Validate ``MCP_UPSTREAM_URL`` using the comma-separated host allowlist env."""
    return assert_upstream_url_safe(url, http_allowed_hosts=env_http_allowed_hosts())


def env_http_allowed_hosts() -> frozenset[str]:
    """HTTP hosts from ``MCP_UPSTREAM_HTTP_ALLOWED_HOSTS``; defaults when unset."""
    raw = os.environ.get("MCP_UPSTREAM_HTTP_ALLOWED_HOSTS", "")
    parsed = frozenset(part.strip().lower() for part in raw.split(",") if part.strip())
    return parsed or _DEFAULT_HTTP_HOSTS


def _require_safe_host(parsed: ParseResult) -> str:
    scheme = (parsed.scheme or "").lower()
    host = (parsed.hostname or "").strip().lower().rstrip(".")
    if scheme not in {"http", "https"}:
        raise UnsafeUpstreamUrlError(f"Denied upstream scheme {scheme!r}")
    if not host:
        raise UnsafeUpstreamUrlError("MCP_UPSTREAM_URL must include a hostname")
    if parsed.username or parsed.password:
        raise UnsafeUpstreamUrlError("MCP_UPSTREAM_URL must not embed credentials")
    if host in _BLOCKED_HOSTNAMES:
        raise UnsafeUpstreamUrlError(f"Denied upstream host {host!r}")
    _assert_ip_not_ssrf_pivot(host)
    return host


def _assert_ip_not_ssrf_pivot(host: str) -> None:
    try:
        addr = ipaddress.ip_address(host)
    except ValueError:
        return
    if addr.is_link_local or addr.is_unspecified or addr.is_multicast:
        raise UnsafeUpstreamUrlError(f"Denied non-routable upstream IP {host!r}")
    if addr in ipaddress.ip_network("169.254.0.0/16"):
        raise UnsafeUpstreamUrlError(f"Denied metadata upstream IP {host!r}")


def _resolve_http_hosts(http_allowed_hosts: Collection[str] | None) -> frozenset[str]:
    if http_allowed_hosts is None:
        return _DEFAULT_HTTP_HOSTS
    return frozenset(host.strip().lower() for host in http_allowed_hosts if str(host).strip())


def _http_host_allowed(host: str, http_hosts: frozenset[str]) -> bool:
    return host in http_hosts or _host_is_loopback_ip(host)


def _host_is_loopback_ip(host: str) -> bool:
    if host in _LOOPBACK_HOSTS:
        return True
    try:
        return ipaddress.ip_address(host).is_loopback
    except ValueError:
        return False

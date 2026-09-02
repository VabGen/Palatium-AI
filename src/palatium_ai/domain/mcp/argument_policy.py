# src/palatium_ai/domain/mcp/argument_policy.py

"""Guardrails for LLM-built MCP tool arguments (never trust model output alone)."""

from __future__ import annotations

import ipaddress
import re

from urllib.parse import urlparse

# Exact key names (case-insensitive) that must never be passed from LLM args.
_DENIED_ARGUMENT_KEYS: frozenset[str] = frozenset(
    {
        "password",
        "passwd",
        "secret",
        "token",
        "access_token",
        "refresh_token",
        "api_key",
        "apikey",
        "authorization",
        "auth",
        "private_key",
        "privatekey",
        "client_secret",
        "credential",
        "credentials",
        "ssn",
        "credit_card",
        "card_number",
        "cvv",
    }
)

# Suffix / substring markers (case-insensitive) for nested keys.
_DENIED_KEY_MARKERS: tuple[str, ...] = (
    "password",
    "secret",
    "api_key",
    "apikey",
    "private_key",
    "access_token",
    "refresh_token",
    "authorization",
)

# Keys whose string values are treated as URLs / filesystem paths.
_LOCATION_KEY_MARKERS: tuple[str, ...] = (
    "url",
    "uri",
    "href",
    "endpoint",
    "webhook",
    "callback",
    "host",
    "hostname",
    "path",
    "filepath",
    "filename",
    "file",
    "directory",
    "dir",
)

_BLOCKED_HOSTNAMES: frozenset[str] = frozenset(
    {
        "localhost",
        "metadata.google.internal",
        "metadata",
    }
)

_PATH_TRAVERSAL = re.compile(r"(^|[/\\])\.\.([/\\]|$)")
_ABSOLUTE_URI = re.compile(r"^[a-zA-Z][a-zA-Z0-9+.-]*:")
# Inline secret material in otherwise-allowed string values (020).
_SECRET_VALUE_PATTERNS: tuple[re.Pattern[str], ...] = (
    re.compile(r"(?i)\bsk-[a-z0-9]{16,}\b"),
    re.compile(r"\bAKIA[0-9A-Z]{16}\b"),
    re.compile(r"(?i)\bpassword\s*=\s*\S+"),
    re.compile(r"(?i)\bapi[_-]?key\s*=\s*\S+"),
    re.compile(r"(?i)\bbearer\s+[a-z0-9\-._~+/]+=*"),
)


class UnsafeToolArgumentError(ValueError):
    """Raised when generated tool arguments include denied sensitive keys."""


def assert_arguments_safe(arguments: dict[str, object], *, path: str = "") -> None:
    """Reject arguments that contain sensitive keys or unsafe location values.

    Schema validation alone is insufficient: an LLM can still invent keys when
    `additionalProperties` is true, or nest secrets / SSRF targets under allowed fields.
    """
    for key, value in arguments.items():
        key_path = f"{path}.{key}" if path else key
        if _is_denied_key(key):
            raise UnsafeToolArgumentError(f"Denied sensitive tool argument key at {key_path!r}")
        if isinstance(value, dict):
            assert_arguments_safe(value, path=key_path)
        elif isinstance(value, list):
            for index, item in enumerate(value):
                if isinstance(item, dict):
                    assert_arguments_safe(item, path=f"{key_path}[{index}]")
                elif isinstance(item, str):
                    _assert_string_value_safe(key=key, value=item, path=f"{key_path}[{index}]")
        elif isinstance(value, str):
            _assert_string_value_safe(key=key, value=value, path=key_path)


def is_sensitive_argument_key(key: str) -> bool:
    """Return True when a tool-argument key must never be echoed to clients or prompts."""
    normalized = key.strip().lower().replace("-", "_")
    if normalized in _DENIED_ARGUMENT_KEYS:
        return True
    return any(marker in normalized for marker in _DENIED_KEY_MARKERS)


def contains_secret_value(value: str) -> bool:
    """Return True when a string looks like embedded credential material."""
    stripped = value.strip()
    if not stripped:
        return False
    return any(pattern.search(stripped) for pattern in _SECRET_VALUE_PATTERNS)


def _is_denied_key(key: str) -> bool:
    return is_sensitive_argument_key(key)


def _is_location_key(key: str) -> bool:
    normalized = key.strip().lower().replace("-", "_")
    return any(marker in normalized for marker in _LOCATION_KEY_MARKERS)


def _assert_string_value_safe(*, key: str, value: str, path: str) -> None:
    stripped = value.strip()
    if not stripped:
        return
    if contains_secret_value(stripped):
        raise UnsafeToolArgumentError(f"Denied secret-shaped value in tool argument at {path!r}")
    # Any absolute URI-shaped string is checked for dangerous schemes / SSRF hosts.
    if _ABSOLUTE_URI.match(stripped) or "://" in stripped:
        _assert_uri_safe(stripped, path=path)
        return
    if not _is_location_key(key):
        return
    if _PATH_TRAVERSAL.search(stripped.replace("\\", "/")):
        raise UnsafeToolArgumentError(f"Denied path traversal in tool argument at {path!r}")
    # Absolute local paths via location keys (Unix / Windows).
    if stripped.startswith(("/", "\\\\")) or re.match(r"^[A-Za-z]:[\\/]", stripped):
        raise UnsafeToolArgumentError(f"Denied absolute filesystem path in tool argument at {path!r}")


def _assert_uri_safe(raw: str, *, path: str) -> None:
    try:
        parsed = urlparse(raw)
    except ValueError as exc:
        raise UnsafeToolArgumentError(f"Denied malformed URI in tool argument at {path!r}") from exc
    scheme = (parsed.scheme or "").lower()
    if scheme and scheme not in {"http", "https"}:
        raise UnsafeToolArgumentError(f"Denied URI scheme {scheme!r} in tool argument at {path!r}")
    host = (parsed.hostname or "").strip().lower().rstrip(".")
    if not host:
        return
    if host in _BLOCKED_HOSTNAMES or host.endswith(".localhost"):
        raise UnsafeToolArgumentError(f"Denied loopback/metadata host in tool argument at {path!r}")
    try:
        addr = ipaddress.ip_address(host)
    except ValueError:
        return
    # Block classic SSRF pivots; allow RFC1918 for enterprise MCP targets.
    if addr.is_loopback or addr.is_link_local or addr.is_unspecified or addr.is_multicast:
        raise UnsafeToolArgumentError(f"Denied non-routable IP in tool argument at {path!r}")

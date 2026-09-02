# src/palatium_ai/core/logging/redact.py

"""Structlog secret redaction (never echo credentials into logs)."""

from __future__ import annotations

import re

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    import logging

    from structlog.types import EventDict

_REDACTED = "[REDACTED]"
_MAX_DEPTH = 6

_SENSITIVE_KEYS: frozenset[str] = frozenset(
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
        "jwt_secret",
        "hmac_secret",
        "signing_secret",
        "bearer",
        "server_auth_tokens",
        "auth_token",
    }
)

_SENSITIVE_KEY_MARKERS: tuple[str, ...] = (
    "password",
    "secret",
    "api_key",
    "apikey",
    "private_key",
    "access_token",
    "refresh_token",
    "authorization",
    "bearer",
)

_SECRET_VALUE_PATTERNS: tuple[re.Pattern[str], ...] = (
    re.compile(r"(?i)\bsk-[a-z0-9]{16,}\b"),
    re.compile(r"\bAKIA[0-9A-Z]{16}\b"),
    re.compile(r"(?i)\bpassword\s*=\s*\S+"),
    re.compile(r"(?i)\bapi[_-]?key\s*=\s*\S+"),
    re.compile(r"(?i)\bbearer\s+[a-z0-9\-._~+/]+=*"),
)


def redact_secrets(
    _logger: logging.Logger,
    _method_name: str,
    event_dict: EventDict,
) -> EventDict:
    """Strip credential-shaped keys/values from a structlog event dict."""
    return _redact_mapping(event_dict, depth=0)


def redact_text(value: str) -> str:
    """Redact secret-shaped substrings in a free-form string (e.g. exception text)."""
    redacted = value
    for pattern in _SECRET_VALUE_PATTERNS:
        redacted = pattern.sub(_REDACTED, redacted)
    return redacted


def _is_sensitive_key(key: str) -> bool:
    normalized = key.strip().lower().replace("-", "_")
    if normalized in _SENSITIVE_KEYS:
        return True
    return any(marker in normalized for marker in _SENSITIVE_KEY_MARKERS)


def _redact_mapping(data: EventDict, *, depth: int) -> EventDict:
    if depth > _MAX_DEPTH:
        return data
    out: EventDict = {}
    for key, value in data.items():
        if isinstance(key, str) and _is_sensitive_key(key):
            out[key] = _REDACTED
            continue
        out[key] = _redact_value(value, depth=depth + 1)
    return out


def _redact_value(value: object, *, depth: int) -> object:
    if depth > _MAX_DEPTH:
        return _REDACTED
    if isinstance(value, dict):
        return _redact_mapping(value, depth=depth)
    if isinstance(value, list):
        return [_redact_value(item, depth=depth + 1) for item in value]
    if isinstance(value, tuple):
        return tuple(_redact_value(item, depth=depth + 1) for item in value)
    if isinstance(value, str):
        return redact_text(value)
    return value

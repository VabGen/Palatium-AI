"""Redact MCP tool-call payloads before exposing them on public APIs.

Stored rows may keep full arguments/content for ops retention; HTTP responses
must not echo secrets or unbounded tool dumps to the client.
"""

from __future__ import annotations

from collections.abc import Mapping

from palatium_ai.domain.mcp.argument_policy import contains_secret_value, is_sensitive_argument_key

# Public API budgets (not DB retention limits).
_MAX_ARG_STRING_CHARS = 256
_MAX_CONTENT_TEXT_CHARS = 512
_MAX_CONTENT_ITEMS = 8
_REDACTED = "[REDACTED]"
_TRUNCATED_SUFFIX = "…[truncated]"

JsonObject = dict[str, object]


def redact_mcp_arguments(arguments: Mapping[str, object] | None) -> JsonObject:
    """Return a client-safe copy of tool arguments."""
    if not arguments:
        return {}
    redacted = _redact_value(dict(arguments), depth=0)
    return redacted if isinstance(redacted, dict) else {}


def redact_mcp_content(content: list[Mapping[str, object]] | None) -> list[JsonObject]:
    """Return a client-safe copy of MCP content blocks."""
    if not content:
        return []
    out: list[JsonObject] = []
    for item in content[:_MAX_CONTENT_ITEMS]:
        if not isinstance(item, Mapping):
            continue
        out.append(_redact_content_item(dict(item)))
    if len(content) > _MAX_CONTENT_ITEMS:
        out.append(
            {
                "type": "text",
                "text": f"[omitted {len(content) - _MAX_CONTENT_ITEMS} content blocks]",
            }
        )
    return out


def _redact_content_item(item: JsonObject) -> JsonObject:
    redacted: JsonObject = {}
    for key, value in item.items():
        key_s = str(key)
        if _is_sensitive_key(key_s):
            redacted[key_s] = _REDACTED
            continue
        if key_s == "text" and isinstance(value, str):
            redacted[key_s] = _truncate(value, _MAX_CONTENT_TEXT_CHARS)
            continue
        redacted[key_s] = _redact_value(value, depth=1)
    return redacted


def _redact_value(value: object, *, depth: int) -> object:
    if depth > 6:
        return "[depth-limit]"
    if isinstance(value, dict):
        out: JsonObject = {}
        for key, nested in list(value.items())[:48]:
            key_s = str(key)
            if _is_sensitive_key(key_s):
                out[key_s] = _REDACTED
            else:
                out[key_s] = _redact_value(nested, depth=depth + 1)
        return out
    if isinstance(value, list):
        return [_redact_value(item, depth=depth + 1) for item in value[:32]]
    if isinstance(value, str):
        if contains_secret_value(value) or _looks_like_secret(value):
            return _REDACTED
        return _truncate(value, _MAX_ARG_STRING_CHARS)
    return value


def _is_sensitive_key(key: str) -> bool:
    return is_sensitive_argument_key(key)


def _looks_like_secret(value: str) -> bool:
    """Legacy short checks kept for Bearer / sk- prefixes."""
    stripped = value.strip()
    if stripped.startswith("sk-") and len(stripped) > 16:
        return True
    return stripped.startswith("Bearer ") and len(stripped) > 20


def _truncate(text: str, max_chars: int) -> str:
    if len(text) <= max_chars:
        return text
    keep = max(0, max_chars - len(_TRUNCATED_SUFFIX))
    return text[:keep] + _TRUNCATED_SUFFIX

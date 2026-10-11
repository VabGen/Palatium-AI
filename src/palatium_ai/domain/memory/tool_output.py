# src/palatium_ai/domain/memory/tool_output.py

"""Compress tool/MCP/worker text before downstream LLM hops (Headroom-style).

Pure domain policy: normalize, compact JSON, truncate with explicit marker —
no phrase lists, no agent-specific branches.
"""

from __future__ import annotations

import json
import re

from typing import Any

_BLANK_LINES = re.compile(r"\n{3,}")
_DUPLICATE_LINE = re.compile(r"(?m)^(.+)\n\1(?:\n|$)")


_UNTRUSTED_OPEN = "<<<UNTRUSTED_TOOL_OUTPUT source={source}>>>"
_UNTRUSTED_CLOSE = "<<<END_UNTRUSTED_TOOL_OUTPUT>>>"


def wrap_untrusted_tool_output(text: str, *, source: str) -> str:
    """Fence external tool text so downstream LLMs treat it as data, not instructions."""
    cleaned = _normalize_text(text)
    if not cleaned:
        return cleaned
    safe_source = "".join(ch if ch.isalnum() or ch in "._:-" else "_" for ch in source.strip())[:128]
    label = safe_source or "tool"
    # Neutralize fence breakout attempts inside the payload.
    body = cleaned.replace(_UNTRUSTED_CLOSE, "[redacted-end-fence]")
    return f"{_UNTRUSTED_OPEN.format(source=label)}\n{body}\n{_UNTRUSTED_CLOSE}"


def contains_untrusted_tool_output(text: str | None) -> bool:
    """Return True when text includes an untrusted-tool fence (evidence, not instructions)."""
    if not text:
        return False
    return "<<<UNTRUSTED_TOOL_OUTPUT" in text and _UNTRUSTED_CLOSE in text


_UNTRUSTED_OPEN_MARK = "<<<UNTRUSTED_TOOL_OUTPUT"


def strip_untrusted_tool_output(text: str) -> str:
    """Drop closed envelope markers and keep the inner body.

    Unclosed markers stay: a user may quote the marker, and deleting that
    tail would drop their text. Only the verbatim researcher path calls this.
    """
    if not text:
        return text
    pieces: list[str] = []
    cursor = 0
    while cursor < len(text):
        start = text.find(_UNTRUSTED_OPEN_MARK, cursor)
        if start < 0:
            pieces.append(text[cursor:])
            break
        header_end = text.find(">>>", start + len(_UNTRUSTED_OPEN_MARK))
        if header_end < 0:
            pieces.append(text[cursor:])
            break
        body_start = header_end + 3
        close_at = text.find(_UNTRUSTED_CLOSE, body_start)
        if close_at < 0:
            pieces.append(text[cursor:])
            break
        pieces.append(text[cursor:start])
        pieces.append(text[body_start:close_at])
        cursor = close_at + len(_UNTRUSTED_CLOSE)
    return "".join(pieces)


def compress_worker_context(
    text: str,
    *,
    max_chars: int,
    label: str = "context",
) -> str:
    """Fit worker/tool text into a char budget for Formatter/Critic/Researcher LLM."""
    if max_chars < 64:
        raise ValueError("max_chars must be >= 64")
    cleaned = _normalize_text(text)
    if not cleaned:
        return cleaned

    compact_json = _compact_json_if_possible(cleaned, max_chars=max_chars)
    if compact_json is not None:
        return compact_json

    if len(cleaned) <= max_chars:
        return cleaned

    return _truncate_edges(cleaned, max_chars=max_chars, label=label)


def _normalize_text(text: str) -> str:
    stripped = text.strip()
    if not stripped:
        return ""
    collapsed = _BLANK_LINES.sub("\n\n", stripped)
    while True:
        deduped = _DUPLICATE_LINE.sub(r"\1\n", collapsed)
        if deduped == collapsed:
            break
        collapsed = deduped
    return collapsed


def _compact_json_if_possible(text: str, *, max_chars: int) -> str | None:
    if not text.startswith(("{", "[")):
        return None
    try:
        payload = json.loads(text)
    except json.JSONDecodeError:
        return None
    compact = json.dumps(payload, ensure_ascii=False, separators=(",", ":"))
    if len(compact) <= max_chars:
        return compact
    return _truncate_json_values(payload, max_chars=max_chars)


def _truncate_json_values(payload: Any, *, max_chars: int) -> str:
    """Shrink string leaves, then compact-serialize; fall back to edge truncate."""
    trimmed = _trim_string_leaves(payload, remaining=max_chars * 2)
    compact = json.dumps(trimmed, ensure_ascii=False, separators=(",", ":"))
    if len(compact) <= max_chars:
        return compact
    return _truncate_edges(compact, max_chars=max_chars, label="json")


def _trim_string_leaves(value: Any, *, remaining: int) -> Any:
    if isinstance(value, str):
        if len(value) <= remaining:
            return value
        keep = max(32, remaining // 4)
        return value[:keep] + f"…[{len(value) - keep} trimmed]"
    if isinstance(value, list):
        return [_trim_string_leaves(item, remaining=remaining) for item in value[:32]]
    if isinstance(value, dict):
        return {str(key): _trim_string_leaves(item, remaining=remaining) for key, item in list(value.items())[:48]}
    return value


def _truncate_edges(text: str, *, max_chars: int, label: str) -> str:
    if len(text) <= max_chars:
        return text
    omitted = len(text) - max_chars
    marker = f"\n… [{label} truncated {omitted} chars] …\n"
    if max_chars <= len(marker) + 24:
        return text[:max_chars]
    keep = (max_chars - len(marker)) // 2
    return f"{text[:keep]}{marker}{text[-keep:]}"

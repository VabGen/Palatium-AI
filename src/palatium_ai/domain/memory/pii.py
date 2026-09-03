# src/palatium_ai/domain/memory/pii.py

"""PII masking + write-time classification for memory (060)."""

from __future__ import annotations

import re

PII_PLACEHOLDER = "[PII]"

_MEMORY_TEXT_KEYS: tuple[str, ...] = ("text", "content", "body", "summary")

# Structured detectors only (not UX phrase lists) — 055/020.
_EMAIL_RE = re.compile(r"\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}\b")
_PHONE_RE = re.compile(r"(?<!\d)(?:\+?\d[\d\-\s()]{8,}\d)(?!\d)")
_PASSPORT_LIKE_RE = re.compile(r"\b(?:passport|паспорт)\s*[:#]?\s*[A-Z0-9]{5,}\b", re.IGNORECASE)


def text_looks_like_pii(text: str) -> bool:
    """Conservative heuristic for write-time PII classification."""
    blob = text.strip()
    if not blob:
        return False
    return bool(_EMAIL_RE.search(blob) or _PHONE_RE.search(blob) or _PASSPORT_LIKE_RE.search(blob))


def resolve_contains_pii(*, text: str, client_flag: bool = False) -> bool:
    """Client may escalate to true; false is never trusted without server scan."""
    return bool(client_flag) or text_looks_like_pii(text)


def memory_contains_pii(value: dict[str, object], *, column_flag: bool = False) -> bool:
    """Whether the record should be masked on read."""
    return column_flag or bool(value.get("contains_pii", False))


def mask_memory_value(
    value: dict[str, object],
    *,
    contains_pii: bool = False,
) -> dict[str, object]:
    """Return a copy safe for LLM context when PII is flagged."""
    if not memory_contains_pii(value, column_flag=contains_pii):
        return value
    masked = dict(value)
    for key in _MEMORY_TEXT_KEYS:
        if key in masked and isinstance(masked[key], str):
            masked[key] = PII_PLACEHOLDER
    return masked

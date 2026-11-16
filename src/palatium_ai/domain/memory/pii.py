# src/palatium_ai/domain/memory/pii.py

"""PII masking + write-time classification for memory (060).

Patterns live in ``domain/pii`` (one registry for every boundary); this module keeps the
memory-facing names and the whole-record masking contract, so callers and tests do not
grow a second import path (010).
"""

from __future__ import annotations

from pydantic import BaseModel

from palatium_ai.core.security.pii import (
    PiiKind,
    contains_pii as _pii_detected,
    scan_pii,
    scrub_pii,
)

PII_PLACEHOLDER = "[PII]"

_MEMORY_TEXT_KEYS: tuple[str, ...] = ("text", "content", "body", "summary")


class PiiClassification(BaseModel):
    """Write-gate result: the flag plus the classes that raised it.

    The kinds are what makes the gate observable — ``contains_pii=true`` alone cannot
    tell an operator whether emails or account numbers are being stored (040).
    """

    model_config = {"frozen": True}

    contains: bool
    kinds: tuple[PiiKind, ...] = ()


def classify_pii(*, text: str, client_flag: bool = False) -> PiiClassification:
    """Classify text for storage; a client ``True`` may escalate, never de-escalate."""
    scan = scan_pii(text.strip(), profile="strict")
    return PiiClassification(contains=bool(client_flag) or scan.found, kinds=scan.kinds)


def text_looks_like_pii(text: str) -> bool:
    """Conservative heuristic for write-time PII classification."""
    return _pii_detected(text.strip(), profile="strict")


def mask_pii_in_text(text: str) -> str:
    """Replace structured PII detectors with stable placeholders (attachments G06, 060)."""
    return scrub_pii(text, profile="strict", style="bracket")


def resolve_contains_pii(*, text: str, client_flag: bool = False) -> bool:
    """Client may escalate to true; false is never trusted without server scan."""
    return classify_pii(text=text, client_flag=client_flag).contains


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

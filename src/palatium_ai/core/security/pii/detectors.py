# src/palatium_ai/domain/pii/detectors.py

"""The one registry of PII patterns (020) — every boundary reads it, none copies it.

Each detector declares the *profiles* it belongs to, so a boundary difference is a
subset of one table (a claim about precision), not a second table with its own drift.
Declaration order is precedence: the first detector to claim a span wins, which is what
keeps ``УНП 123456789`` a tax id instead of a phone number.
"""

from __future__ import annotations

import re

from collections.abc import Callable, Iterator

from palatium_ai.core.security.pii.models import PiiKind, PiiMaskStyle, PiiProfile

_BOTH = frozenset[PiiProfile]({"strict", "observability"})
_LOG_ONLY = frozenset[PiiProfile]({"observability"})

_CARD_MIN_DIGITS = 13
_CARD_MAX_DIGITS = 19

_PLACEHOLDERS: dict[PiiMaskStyle, dict[PiiKind, str]] = {
    # Storage text (memory, attachment body): readable, bracketed.
    "bracket": {
        "email": "[EMAIL]",
        "phone": "[PHONE]",
        "iban": "[IBAN]",
        "tax_id": "[ID]",
        "card": "[CARD]",
        "passport": "[ID]",
    },
    # Log/trace text: the vocabulary the dashboards already grep for.
    "angle": {
        "email": "<email>",
        "phone": "<phone>",
        "iban": "<iban_by>",
        "tax_id": "<unp>",
        "card": "<card>",
        "passport": "<passport>",
    },
}


def _luhn_valid(raw: str) -> bool:
    """Checksum gate: a card is a card, not an order or tracking number."""
    digits = [int(char) for char in raw if char.isdigit()]
    if not _CARD_MIN_DIGITS <= len(digits) <= _CARD_MAX_DIGITS:
        return False
    checksum = 0
    for position, digit in enumerate(reversed(digits)):
        if position % 2 == 1:
            digit *= 2
            if digit > 9:
                digit -= 9
        checksum += digit
    return checksum % 10 == 0


class Detector:
    """One named PII class: pattern, precision gate, applicable profiles."""

    __slots__ = ("_kind", "_pattern", "_profiles", "_validate")

    def __init__(
        self,
        kind: PiiKind,
        pattern: re.Pattern[str],
        *,
        profiles: frozenset[PiiProfile],
        validate: Callable[[str], bool] | None = None,
    ) -> None:
        self._kind = kind
        self._pattern = pattern
        self._profiles = profiles
        self._validate = validate

    @property
    def kind(self) -> PiiKind:
        return self._kind

    def applies_to(self, profile: PiiProfile) -> bool:
        return profile in self._profiles

    def matches(self, text: str) -> Iterator[tuple[int, int]]:
        """Yield ``(start, end)`` of accepted spans in declaration-independent order."""
        for match in self._pattern.finditer(text):
            if self._validate is not None and not self._validate(match.group(0)):
                continue
            yield match.start(), match.end()


DETECTORS: tuple[Detector, ...] = (
    # Email: the only pattern both boundaries had, identical in each.
    Detector("email", re.compile(r"\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}\b"), profiles=_BOTH),
    # BY УНП — 9 digits. Log-only: in stored text it is indistinguishable from an id/date.
    Detector("tax_id", re.compile(r"\b\d{9}\b"), profiles=_LOG_ONLY),
    # BY IBAN. Newly visible to classification: a stored account number is PII (R3).
    Detector("iban", re.compile(r"\bBY\d{2}[A-Z0-9]{4,28}\b"), profiles=_BOTH),
    # Card before phone: a Luhn-valid 16-digit run must be named a card, not a phone.
    Detector(
        "card",
        re.compile(r"(?<!\w)(?:\d[ -]?){12,18}\d(?!\w)"),
        profiles=_BOTH,
        validate=_luhn_valid,
    ),
    # At least 10 digits: storage classification must not mistake a 9-digit id for a
    # phone (logs mask bare 9 digits as ``tax_id`` first, so nothing is lost there).
    Detector("phone", re.compile(r"(?<!\w)\+?\d[\d\s\-()]{8,}\d(?!\w)"), profiles=_BOTH),
    Detector(
        "passport",
        re.compile(r"\b(?:passport|паспорт)\s*[:#]?\s*[A-Z0-9]{5,}\b", re.IGNORECASE),
        profiles=_BOTH,
    ),
)


def detectors_for(profile: PiiProfile) -> tuple[Detector, ...]:
    return tuple(detector for detector in DETECTORS if detector.applies_to(profile))


def placeholder_for(kind: PiiKind, style: PiiMaskStyle) -> str:
    return _PLACEHOLDERS[style][kind]


__all__ = ["DETECTORS", "Detector", "detectors_for", "placeholder_for"]

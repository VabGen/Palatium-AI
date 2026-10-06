# src/palatium_ai/domain/memory/emotional.py

"""Optional emotional metadata on medium entries (Wave M8).

Never required on write (plan reject: mandatory valence). When present,
must be a float in [-1, 1].
"""

from __future__ import annotations

from palatium_ai.core.types.coerce import coerce_float


def parse_optional_emotional_valence(raw: object) -> float | None:
    """Return valence in [-1, 1], ``None`` if absent, or raise ``ValueError``."""
    if raw is None:
        return None
    if isinstance(raw, str) and not raw.strip():
        return None
    value = coerce_float(raw)
    if value < -1.0 or value > 1.0:
        msg = "emotional_valence must be in [-1, 1]"
        raise ValueError(msg)
    return value

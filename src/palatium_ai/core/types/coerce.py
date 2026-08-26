# src/palatium_ai/core/types/coerce.py

"""Safe coercions from untyped dict values (MemoryPort / JSON payloads)."""

from __future__ import annotations


def coerce_float(value: object, default: float = 0.0) -> float:
    """Convert object to float; return default on failure."""
    if isinstance(value, bool):
        return float(value)
    if isinstance(value, (int, float)):
        return float(value)
    if isinstance(value, str):
        try:
            return float(value)
        except ValueError:
            return default
    return default

# src/palatium_ai/domain/memory/hebbian.py

"""Hebbian edge weight bump for promote batch (Wave M8, eval-gated)."""

from __future__ import annotations


def bump_hebbian_weight(
    current: float,
    *,
    learning_rate: float = 0.1,
) -> float:
    """Asymptotic bump toward 1.0: ``w + η(1 − w)`` clamped to [0, 1]."""
    w = max(0.0, min(1.0, float(current)))
    eta = max(0.0, min(1.0, float(learning_rate)))
    return max(0.0, min(1.0, w + eta * (1.0 - w)))

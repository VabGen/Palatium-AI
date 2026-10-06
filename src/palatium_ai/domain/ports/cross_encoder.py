# src/palatium_ai/domain/ports/cross_encoder.py

"""Cross-encoder rerank port (Wave M8) — optional, not hot-path default."""

from __future__ import annotations

from typing import Protocol


class CrossEncoderPort(Protocol):
    """Score (query, passage) pairs; higher is more relevant."""

    async def score_pairs(self, *, query: str, passages: list[str]) -> list[float]:
        """Return one score per passage (same order)."""
        ...

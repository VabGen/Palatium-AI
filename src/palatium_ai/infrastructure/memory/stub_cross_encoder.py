# src/palatium_ai/infrastructure/memory/stub_cross_encoder.py

"""Deterministic CrossEncoderPort for tests / local smoke (Wave M8)."""

from __future__ import annotations


class TokenOverlapCrossEncoder:
    """Cheap CE stand-in: score = overlap of query tokens in passage (0..1)."""

    async def score_pairs(self, *, query: str, passages: list[str]) -> list[float]:
        tokens = {t for t in query.lower().split() if len(t) >= 2}
        if not tokens:
            return [0.0] * len(passages)
        out: list[float] = []
        for passage in passages:
            blob = passage.lower()
            hits = sum(1 for token in tokens if token in blob)
            out.append(hits / float(len(tokens)))
        return out

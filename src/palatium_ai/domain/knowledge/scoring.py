# src/palatium_ai/domain/knowledge/scoring.py

"""Hybrid ranking for knowledge chunk retrieval (060 — single source)."""

from __future__ import annotations


def merge_hybrid_knowledge_hits(
    fts_hits: list[tuple[str, float, dict[str, object]]],
    vector_hits: list[tuple[str, float, dict[str, object]]],
    *,
    limit: int,
) -> list[dict[str, object]]:
    """Merge FTS and vector hits by chunk key; keep best blended score."""
    merged: dict[str, tuple[float, dict[str, object]]] = {}
    for chunk_key, score, payload in fts_hits:
        merged[chunk_key] = (score * 0.35, payload)
    for chunk_key, score, payload in vector_hits:
        current = merged.get(chunk_key)
        blended = (current[0] if current else 0.0) + score * 0.65
        merged[chunk_key] = (blended, current[1] if current else payload)
    ranked = sorted(merged.values(), key=lambda item: item[0], reverse=True)
    return [_with_score(payload, score) for score, payload in ranked[:limit]]


def _with_score(payload: dict[str, object], score: float) -> dict[str, object]:
    enriched = dict(payload)
    enriched["score"] = round(min(1.0, max(0.0, score)), 4)
    return enriched

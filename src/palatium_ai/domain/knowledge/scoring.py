# src/palatium_ai/domain/knowledge/scoring.py

"""Hybrid ranking for knowledge chunk retrieval (060 — single source)."""

from __future__ import annotations

from palatium_ai.core.types.knowledge import DEFAULT_RRF_K, KnowledgeHybridFusion

__all__ = ["DEFAULT_RRF_K", "KnowledgeHybridFusion", "merge_hybrid_knowledge_hits"]


def merge_hybrid_knowledge_hits(
    fts_hits: list[tuple[str, float, dict[str, object]]],
    vector_hits: list[tuple[str, float, dict[str, object]]],
    *,
    limit: int,
    fusion: KnowledgeHybridFusion = "weighted",
    rrf_k: int = DEFAULT_RRF_K,
) -> list[dict[str, object]]:
    """Merge FTS and vector hits by chunk key.

    ``weighted`` — legacy blend (0.35 FTS + 0.65 dense).
    ``rrf`` — Reciprocal Rank Fusion over ranks (score-independent; 2026 baseline).
    """
    if fusion == "rrf":
        return _merge_rrf(fts_hits, vector_hits, limit=limit, rrf_k=rrf_k)
    return _merge_weighted(fts_hits, vector_hits, limit=limit)


def _merge_weighted(
    fts_hits: list[tuple[str, float, dict[str, object]]],
    vector_hits: list[tuple[str, float, dict[str, object]]],
    *,
    limit: int,
) -> list[dict[str, object]]:
    merged: dict[str, tuple[float, dict[str, object]]] = {}
    for chunk_key, score, payload in fts_hits:
        merged[chunk_key] = (score * 0.35, payload)
    for chunk_key, score, payload in vector_hits:
        current = merged.get(chunk_key)
        blended = (current[0] if current else 0.0) + score * 0.65
        merged[chunk_key] = (blended, current[1] if current else payload)
    ranked = sorted(merged.values(), key=lambda item: item[0], reverse=True)
    return [_with_score(payload, score) for score, payload in ranked[:limit]]


def _merge_rrf(
    fts_hits: list[tuple[str, float, dict[str, object]]],
    vector_hits: list[tuple[str, float, dict[str, object]]],
    *,
    limit: int,
    rrf_k: int,
) -> list[dict[str, object]]:
    """RRF: ``score(d) = Σ 1 / (k + rank_i(d))`` over ranked lists (1-based ranks)."""
    safe_k = max(1, rrf_k)
    scores: dict[str, float] = {}
    payloads: dict[str, dict[str, object]] = {}
    for rank, (chunk_key, _score, payload) in enumerate(fts_hits, start=1):
        scores[chunk_key] = scores.get(chunk_key, 0.0) + 1.0 / (safe_k + rank)
        payloads.setdefault(chunk_key, payload)
    for rank, (chunk_key, _score, payload) in enumerate(vector_hits, start=1):
        scores[chunk_key] = scores.get(chunk_key, 0.0) + 1.0 / (safe_k + rank)
        payloads.setdefault(chunk_key, payload)
    ordered = sorted(scores.items(), key=lambda item: item[1], reverse=True)
    # RRF scores are not probabilities — do not clamp to [0, 1].
    return [_with_score(payloads[key], score, clamp_unit=False) for key, score in ordered[:limit]]


def _with_score(
    payload: dict[str, object],
    score: float,
    *,
    clamp_unit: bool = True,
) -> dict[str, object]:
    enriched = dict(payload)
    value = min(1.0, max(0.0, score)) if clamp_unit else score
    enriched["score"] = round(value, 4)
    return enriched

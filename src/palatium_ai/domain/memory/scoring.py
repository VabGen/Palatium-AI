# src/palatium_ai/domain/memory/scoring.py

"""Importance formula + hybrid merge / search-time ranking (060.2, Wave M2)."""

from __future__ import annotations

import math

from datetime import UTC, datetime
from typing import Any

from pydantic import BaseModel, Field

from palatium_ai.core.types.coerce import coerce_float
from palatium_ai.core.types.retrieval import DEFAULT_RRF_K, HybridFusion

_RECENCY_WEIGHT = 0.4
_RELEVANCE_WEIGHT = 0.4
_FREQUENCY_WEIGHT = 0.2
_FREQUENCY_SATURATION = 10
_DEFAULT_HALF_LIFE_DAYS = 7.0

MemoryHitTuple = tuple[str, float, dict[str, object]]


class ImportanceInputs(BaseModel):
    """Нормализованные компоненты для расчёта importance."""

    model_config = {"frozen": True}

    recency_score: float = Field(ge=0.0, le=1.0)
    relevance_score: float = Field(ge=0.0, le=1.0)
    access_frequency: int = Field(ge=0, default=0)


def recency_score(
    *,
    last_accessed: datetime,
    now: datetime | None = None,
    half_life_days: float = _DEFAULT_HALF_LIFE_DAYS,
) -> float:
    """Экспоненциальное затухание по давности последнего доступа (UTC-aware)."""
    if half_life_days <= 0:
        msg = "half_life_days must be positive"
        raise ValueError(msg)
    reference = now or datetime.now(UTC)
    if last_accessed.tzinfo is None:
        msg = "last_accessed must be timezone-aware"
        raise ValueError(msg)
    if reference.tzinfo is None:
        msg = "now must be timezone-aware"
        raise ValueError(msg)
    age_days = max(0.0, (reference - last_accessed).total_seconds() / 86_400.0)
    decay = math.exp(-math.log(2) * age_days / half_life_days)
    return max(0.0, min(1.0, decay))


def frequency_score(access_frequency: int, *, saturation: int = _FREQUENCY_SATURATION) -> float:
    """Нормализованная частота доступа до насыщения."""
    if saturation <= 0:
        msg = "saturation must be positive"
        raise ValueError(msg)
    if access_frequency <= 0:
        return 0.0
    return min(1.0, access_frequency / float(saturation))


def compute_importance(
    inputs: ImportanceInputs,
    *,
    recency_weight: float = _RECENCY_WEIGHT,
    relevance_weight: float = _RELEVANCE_WEIGHT,
    frequency_weight: float = _FREQUENCY_WEIGHT,
    frequency_saturation: int = _FREQUENCY_SATURATION,
) -> float:
    """Итоговый importance в [0, 1]."""
    total_weight = recency_weight + relevance_weight + frequency_weight
    if total_weight <= 0:
        msg = "weights must sum to a positive value"
        raise ValueError(msg)
    freq = frequency_score(inputs.access_frequency, saturation=frequency_saturation)
    raw = recency_weight * inputs.recency_score + relevance_weight * inputs.relevance_score + frequency_weight * freq
    return max(0.0, min(1.0, raw / total_weight))


def merge_hybrid_memory_hits(
    fts_hits: list[MemoryHitTuple],
    vector_hits: list[MemoryHitTuple],
    *,
    limit: int,
    fusion: HybridFusion = "rrf",
    rrf_k: int = DEFAULT_RRF_K,
    now: datetime | None = None,
    half_life_days: float = _DEFAULT_HALF_LIFE_DAYS,
) -> list[dict[str, object]]:
    """Fuse FTS + vector hits, then rank by search-time ``compute_importance``."""
    safe_limit = max(1, limit)
    if fusion == "rrf":
        fused = _merge_rrf(fts_hits, vector_hits, limit=max(safe_limit * 2, safe_limit), rrf_k=rrf_k)
    else:
        fused = _merge_weighted(fts_hits, vector_hits, limit=max(safe_limit * 2, safe_limit))
    return rank_by_search_importance(
        fused,
        limit=safe_limit,
        now=now,
        half_life_days=half_life_days,
    )


def rank_by_search_importance(
    hits: list[dict[str, object]],
    *,
    limit: int,
    now: datetime | None = None,
    half_life_days: float = _DEFAULT_HALF_LIFE_DAYS,
) -> list[dict[str, object]]:
    """Re-rank hybrid hits with domain importance (relevance + τ-recency + access)."""
    if not hits:
        return []
    reference = now or datetime.now(UTC)
    if reference.tzinfo is None or reference.utcoffset() is None:
        msg = "now must be timezone-aware (UTC)"
        raise ValueError(msg)
    raw_scores = [coerce_float(hit.get("_score", 0.0)) for hit in hits]
    max_score = max(raw_scores)
    min_score = min(raw_scores)
    span = max_score - min_score
    ranked: list[tuple[float, dict[str, object]]] = []
    for hit, raw in zip(hits, raw_scores, strict=True):
        relevance = ((raw - min_score) / span) if span > 0 else (1.0 if max_score > 0 else 0.0)
        accessed = _activity_timestamp(hit, fallback=reference)
        access_frequency = max(0, int(coerce_float(hit.get("_access_frequency", 0))))
        importance = compute_importance(
            ImportanceInputs(
                recency_score=recency_score(
                    last_accessed=accessed,
                    now=reference,
                    half_life_days=half_life_days,
                ),
                relevance_score=relevance,
                access_frequency=access_frequency,
            )
        )
        enriched = dict(hit)
        enriched["_score"] = round(importance, 4)
        enriched["_relevance"] = round(relevance, 4)
        ranked.append((importance, enriched))
    ranked.sort(key=lambda item: item[0], reverse=True)
    return [payload for _, payload in ranked[: max(1, limit)]]


def _merge_weighted(
    fts_hits: list[MemoryHitTuple],
    vector_hits: list[MemoryHitTuple],
    *,
    limit: int,
) -> list[dict[str, object]]:
    """Legacy blend: keep max confidence-adjusted score per entry key."""
    merged: dict[str, tuple[float, dict[str, object]]] = {}
    for entry_key, score, payload in fts_hits + vector_hits:
        current = merged.get(entry_key)
        blended = score * (0.5 + 0.5 * _payload_confidence(payload))
        if current is None or blended > current[0]:
            merged[entry_key] = (blended, payload)
    ordered = sorted(merged.values(), key=lambda item: item[0], reverse=True)
    return [_with_hybrid_score(payload, score) for score, payload in ordered[:limit]]


def _merge_rrf(
    fts_hits: list[MemoryHitTuple],
    vector_hits: list[MemoryHitTuple],
    *,
    limit: int,
    rrf_k: int,
) -> list[dict[str, object]]:
    """RRF: ``score(d) = Σ 1 / (k + rank_i(d))`` over ranked lists (1-based ranks)."""
    safe_k = max(1, rrf_k)
    scores: dict[str, float] = {}
    payloads: dict[str, dict[str, object]] = {}
    for rank, (entry_key, _score, payload) in enumerate(fts_hits, start=1):
        scores[entry_key] = scores.get(entry_key, 0.0) + 1.0 / (safe_k + rank)
        payloads.setdefault(entry_key, payload)
    for rank, (entry_key, _score, payload) in enumerate(vector_hits, start=1):
        scores[entry_key] = scores.get(entry_key, 0.0) + 1.0 / (safe_k + rank)
        payloads.setdefault(entry_key, payload)
    ordered = sorted(scores.items(), key=lambda item: item[1], reverse=True)
    return [_with_hybrid_score(payloads[key], score) for key, score in ordered[:limit]]


def _with_hybrid_score(payload: dict[str, object], score: float) -> dict[str, object]:
    enriched = dict(payload)
    enriched["_score"] = round(score, 4)
    entry_key = str(payload.get("_entry_key", "")).strip()
    if entry_key:
        enriched["_entry_key"] = entry_key
    return enriched


def _payload_confidence(value: dict[str, Any]) -> float:
    return max(0.0, min(1.0, coerce_float(value.get("confidence", 0.0))))


def _activity_timestamp(hit: dict[str, object], *, fallback: datetime) -> datetime:
    for key in ("_last_accessed", "_created_at"):
        raw = hit.get(key)
        if raw is None or raw == "":
            continue
        if isinstance(raw, datetime):
            if raw.tzinfo is None or raw.utcoffset() is None:
                return raw.replace(tzinfo=UTC)
            return raw
        # py3.11+: fromisoformat accepts trailing Z (FURB162).
        parsed = datetime.fromisoformat(str(raw))
        if parsed.tzinfo is None or parsed.utcoffset() is None:
            return parsed.replace(tzinfo=UTC)
        return parsed
    return fallback

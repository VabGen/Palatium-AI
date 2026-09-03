# src/palatium_ai/domain/memory/scoring.py

"""Формула importance: recency + relevance + access_frequency (060.2)."""

from __future__ import annotations

import math

from datetime import UTC, datetime

from pydantic import BaseModel, Field

_RECENCY_WEIGHT = 0.4
_RELEVANCE_WEIGHT = 0.4
_FREQUENCY_WEIGHT = 0.2
_FREQUENCY_SATURATION = 10
_DEFAULT_HALF_LIFE_DAYS = 7.0


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

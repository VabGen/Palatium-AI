# src/palatium_ai/core/types/model_registry.py

"""Model tier → context token budget (065) — единственный источник."""

from __future__ import annotations

from typing import Literal

# Abstract tiers (030 contract).
AbstractModelTier = Literal["frontier", "standard", "fast"]

# Runtime tiers used by AgentConfig today (mapped to abstract tiers below).
RuntimeModelTier = Literal["nano", "small", "mid", "frontier", "deep_reasoning"]

_CONTEXT_LIMIT_BY_ABSTRACT: dict[AbstractModelTier, int] = {
    "fast": 32_000,
    "standard": 128_000,
    "frontier": 200_000,
}

_RUNTIME_TO_ABSTRACT: dict[str, AbstractModelTier] = {
    "nano": "fast",
    "small": "fast",
    "mid": "standard",
    "frontier": "frontier",
    "deep_reasoning": "frontier",
    # 030 aliases (future agents).
    "fast": "fast",
    "standard": "standard",
}


def abstract_tier_for(runtime_tier: str) -> AbstractModelTier:
    """Map runtime AgentConfig.model_tier to abstract frontier|standard|fast."""
    key = (runtime_tier or "standard").strip().lower()
    return _RUNTIME_TO_ABSTRACT.get(key, "standard")


def context_limit_tokens(*, model_tier: str) -> int:
    """JIT context budget for a model tier (065)."""
    abstract = abstract_tier_for(model_tier)
    return _CONTEXT_LIMIT_BY_ABSTRACT[abstract]

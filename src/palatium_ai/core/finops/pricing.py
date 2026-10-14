"""Tier model pricing registry for LiteLLM cost tracking."""

from __future__ import annotations

from typing import Any

from palatium_ai.core.logging import get_logger

logger = get_logger(__name__)


def _cache_costs(input_cost_per_token: float) -> dict[str, float]:
    """Prompt-cache unit costs until the corporate gateway publishes real rates.

    Write ≈ input (conservative); read ≈ 10% of input (common CDN/prefix-cache ratio).
    Replace with billed rates when ``openai/generative-model`` documents them.
    """
    return {
        "cache_creation_input_token_cost": input_cost_per_token,
        "cache_read_input_token_cost": input_cost_per_token * 0.1,
    }


def get_tier_model_specs() -> dict[str, dict[str, Any]]:
    """Return tier model specifications for LiteLLM registration."""
    small_in = 0.00000015  # $0.15 / 1M tokens
    mid_in = 0.0000025  # $2.5 / 1M tokens
    frontier_in = 0.000015  # $15 / 1M tokens
    return {
        "openai/tier-small": {
            "max_tokens": 8192,
            "max_input_tokens": 128000,
            "max_output_tokens": 8192,
            "input_cost_per_token": small_in,
            "output_cost_per_token": 0.00000060,  # $0.60 / 1M tokens
            **_cache_costs(small_in),
            "litellm_provider": "openai",
            "mode": "chat",
        },
        "openai/tier-mid": {
            "max_tokens": 16384,
            "max_input_tokens": 128000,
            "max_output_tokens": 16384,
            "input_cost_per_token": mid_in,
            "output_cost_per_token": 0.000010,  # $10 / 1M tokens
            **_cache_costs(mid_in),
            "litellm_provider": "openai",
            "mode": "chat",
        },
        "openai/tier-frontier": {
            "max_tokens": 32768,
            "max_input_tokens": 200000,
            "max_output_tokens": 32768,
            "input_cost_per_token": frontier_in,
            "output_cost_per_token": 0.000075,  # $75 / 1M tokens
            **_cache_costs(frontier_in),
            "litellm_provider": "openai",
            "mode": "chat",
        },
        "openai/embedding-model": {
            "max_input_tokens": 8192,
            "input_cost_per_token": 0.00000002,  # $0.02 / 1M tokens
            "output_cost_per_token": 0.0,
            **_cache_costs(0.00000002),
            "litellm_provider": "openai",
            "mode": "embedding",
        },
    }


def register_tier_costs() -> None:
    """Register tier models with LiteLLM for cost tracking."""
    try:
        import litellm
    except ImportError:  # pragma: no cover - litellm is a hard dep in prod
        logger.warning("litellm unavailable; tier cost registration skipped")
        return

    for model_name, spec in get_tier_model_specs().items():
        try:
            litellm.register_model({model_name: spec})
            # Bare alias (gateway may return ``tier-small`` without provider prefix).
            bare = model_name.removeprefix("openai/")
            if bare != model_name:
                litellm.register_model({bare: spec})
        except (TypeError, ValueError, AttributeError, KeyError, RuntimeError) as exc:
            logger.warning(
                "failed to register LiteLLM model",
                model=model_name,
                error=str(exc),
            )

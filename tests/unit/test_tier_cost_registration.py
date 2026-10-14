"""Unit tests for LiteLLM tier cost registration (Phase 3)."""

from __future__ import annotations

from unittest.mock import patch

import pytest

from palatium_ai.core.finops.pricing import get_tier_model_specs, register_tier_costs


def test_register_tier_costs() -> None:
    with patch("litellm.register_model") as mock_register:
        register_tier_costs()

        # Qualified + bare alias for each chat/embedding spec.
        assert mock_register.call_count >= 4
        calls = mock_register.call_args_list
        tier_small_spec = calls[0][0][0]["openai/tier-small"]
        assert tier_small_spec["input_cost_per_token"] == 0.00000015
        assert tier_small_spec["cache_creation_input_token_cost"] == 0.00000015
        assert tier_small_spec["cache_read_input_token_cost"] == pytest.approx(0.000000015)


def test_get_tier_model_specs_covers_chat_and_embedding() -> None:
    specs = get_tier_model_specs()
    assert "openai/tier-small" in specs
    assert "openai/tier-mid" in specs
    assert "openai/tier-frontier" in specs
    assert "openai/embedding-model" in specs
    assert specs["openai/embedding-model"]["mode"] == "embedding"
    for key in ("openai/tier-small", "openai/tier-mid", "openai/tier-frontier"):
        assert "cache_creation_input_token_cost" in specs[key]
        assert "cache_read_input_token_cost" in specs[key]

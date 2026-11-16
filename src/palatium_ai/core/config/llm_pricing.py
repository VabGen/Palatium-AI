# src/palatium_ai/core/config/llm_pricing.py

"""Versioned LLM price table surface (W7.2).

SoT rates live in ``core/finops/pricing.py`` (LiteLLM registration). This module
pins a **pricing_version** string so PRs that change rates must carry
``[pricing-update]`` (ADR-0011). Do not invent rates here — re-export only.
"""

from __future__ import annotations

from typing import Any, Final

from palatium_ai.core.finops.pricing import get_tier_model_specs, register_tier_costs

#: Baseline version shipped with ADR-0011. Changes *after* this value require
#: ``[pricing-update]`` in the PR (initial surface itself did not).
PRICING_VERSION: Final[str] = "2026-11-10.1"


def pricing_table() -> dict[str, dict[str, Any]]:
    """Return the current tier price cards (read-only view for tests / FinOps)."""
    return get_tier_model_specs()


__all__ = [
    "PRICING_VERSION",
    "pricing_table",
    "register_tier_costs",
]

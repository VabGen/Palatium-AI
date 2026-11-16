# src/palatium_ai/core/observability/adaptive_grounding.py

"""Sticky per-user Adaptive Grounding rollout (pre-flip hardening).

Does not change GroundingPolicy classify/clarify — only whether the adaptive
path is enabled for this caller.

Two-key semantics (ON iff ENABLED and PCT > 0):
  ENABLED=true,  PCT=0   → OFF (+ startup warning)
  ENABLED=true,  PCT=100 → ON for all (ON-tests / full cutover)
  ENABLED=true,  PCT=10  → sticky ~10% cohort
  ENABLED=false, PCT=*   → OFF

Rollback: set PCT=0 (keep ENABLED=true so re-rollout is one variable).
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import structlog

from palatium_ai.core.config import get_settings
from palatium_ai.core.config.observability import ObservabilityConfig
from palatium_ai.core.observability.metrics import agent_metrics
from palatium_ai.core.observability.redaction import hash8

if TYPE_CHECKING:
    from palatium_ai.core.config.settings import Settings

logger = structlog.get_logger(__name__)


def warn_if_enabled_but_zero_rollout(
    settings: Settings | ObservabilityConfig | None = None,
) -> None:
    """Startup guard: ENABLED=true with PCT=0 is a silent no-op unless warned."""
    obs = _observability(settings)
    if obs.adaptive_grounding_enabled and int(obs.adaptive_grounding_rollout_pct) <= 0:
        logger.warning(
            "adaptive_grounding.enabled_but_zero_rollout",
            hint=(
                "Set ADAPTIVE_GROUNDING_ROLLOUT_PCT > 0 (e.g. 10) for the "
                "feature to take effect; PCT=0 is the intentional rollback path"
            ),
        )


def is_adaptive_grounding_enabled(
    user_id: str | None = None,
    *,
    record: bool = False,
) -> bool:
    """Sticky per-user rollout under two-key control (see module docstring).

    Pass ``record=True`` once per turn (weaving/hop summary) so rollout metrics
    are not tripled by planner + researcher + formatter checks.
    """
    settings = get_settings().observability
    if not settings.adaptive_grounding_enabled:
        enabled = False
    else:
        pct = int(settings.adaptive_grounding_rollout_pct)
        if pct <= 0:
            enabled = False
        elif pct >= 100:
            enabled = True
        else:
            uid = (user_id or "").strip() or "anonymous"
            bucket = int(hash8(uid), 16) % 100
            enabled = bucket < pct
    if record:
        agent_metrics.record_grounding_rollout(enabled=enabled)
    return enabled


def _observability(
    settings: Settings | ObservabilityConfig | None,
) -> ObservabilityConfig:
    if settings is None:
        return get_settings().observability
    if isinstance(settings, ObservabilityConfig):
        return settings
    return settings.observability

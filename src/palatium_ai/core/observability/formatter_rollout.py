# src/palatium_ai/core/observability/formatter_rollout.py

"""Sticky per-user Formatter generation-contract rollout (Phase 3 canary).

Mirrors the Adaptive Grounding two-key semantics (adaptive_grounding.py):
``FORMATTER_MODE`` selects the *target* contract, ``FORMATTER_ROLLOUT_PCT``
selects *coverage*. Replicas are never mixed by hand — a single process serves
both cohorts deterministically per user, so a rolling update cannot flip a
user's contract mid-conversation.

    MODE=schema_first, PCT=100 → schema_first for every caller (full cutover)
    MODE=schema_first, PCT=5   → sticky ~5% of users, rest legacy (canary)
    MODE=schema_first, PCT=0   → legacy for all (rollback; keep MODE to re-roll)
    MODE=legacy,       PCT=*   → legacy for all (hard kill switch)

Rollback is therefore a single variable (PCT=0), and the canary ramps without
a deploy: 5 → 25 → 50 → 100.
"""

from __future__ import annotations

import structlog

from palatium_ai.core.config.formatter import FormatterMode
from palatium_ai.core.observability.redaction import hash8

logger = structlog.get_logger(__name__)

_LEGACY: FormatterMode = "legacy"
_SCHEMA_FIRST: FormatterMode = "schema_first"


def resolve_formatter_mode(
    configured_mode: FormatterMode,
    rollout_pct: int,
    user_id: str | None,
) -> FormatterMode:
    """Return the effective contract for this caller (pure; no I/O)."""
    if configured_mode != _SCHEMA_FIRST:
        return _LEGACY
    pct = int(rollout_pct)
    if pct <= 0:
        return _LEGACY
    if pct >= 100:
        return _SCHEMA_FIRST
    bucket = int(hash8((user_id or "").strip() or "anonymous"), 16) % 100
    return _SCHEMA_FIRST if bucket < pct else _LEGACY


def warn_if_schema_first_but_zero_rollout(formatter_mode: FormatterMode, rollout_pct: int) -> None:
    """Startup guard: MODE=schema_first with PCT=0 is a silent no-op unless warned."""
    if formatter_mode == _SCHEMA_FIRST and int(rollout_pct) <= 0:
        logger.warning(
            "formatter.rollout.zero_coverage",
            hint=(
                "FORMATTER_MODE=schema_first but FORMATTER_ROLLOUT_PCT=0 — the Formatter "
                "stays on the legacy contract. Set PCT>0 (e.g. 5) to run the canary."
            ),
        )

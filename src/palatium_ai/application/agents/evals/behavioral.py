# src/palatium_ai/application/agents/evals/behavioral.py

"""Behavioral baseline loader — hop/handoff (W5) + cost/context (W7) (075).

Contracts this module serves (do not re-invent in callers):

1. **Cost ``None`` ≠ ``0``.** ``actual_cost_usd`` / ``max_cost_usd`` are ``None``
   when ``cost_channel == cassette_unmeasured`` — CI cassette replay does not
   meter USD. That is not «measured zero cost». Production cost regression uses
   ``palatium_llm_cost_usd_total`` (ADR-0011), not this baseline.
2. **``ContextRatioBudget`` is a size regression guard, not isolation proof.**
   Ratio > 1 can be normal (child scaffolding). Isolation policy lives in
   ADR-0009 § Handoff payload + ``assert_fresh_handoff_context`` allow-list
   (ADR-0011 § Fresh context).
3. **``refresh_policy.marker`` = ``[baseline-refresh]``** — the only legal way to
   change ``actual_*`` / ``max_*`` in ``baselines/behavioral.json``. A PR that
   raises ceilings without the marker violates ADR-0010 §5.

SoT JSON: ``baselines/behavioral.json`` (schema_version ≥ 3).
Policy: ADR-0010 (closure / refresh), ADR-0011 (cost & context semantics).
"""

from __future__ import annotations

import json

from dataclasses import dataclass
from pathlib import Path
from typing import Any

_BASELINE_PATH = Path(__file__).resolve().parent / "baselines" / "behavioral.json"

#: Canonical hot-path nodes when Critic runs and no worker is selected:
#: Intent → Continuity → Supervisor → Weaver → Critic → Formatter.
_BASE_PIPELINE_STEPS = 6


@dataclass(frozen=True)
class RouteBudget:
    """Measured topology + regression ceiling for one route (W5.1 / W7.2).

    ``actual_cost_usd`` / ``max_cost_usd`` are ``None`` when
    ``cost_channel == cassette_unmeasured`` (CI replay does not meter USD).
    """

    actual_steps: int
    actual_handoffs: int
    max_steps: int
    max_handoffs: int
    max_subagent_depth: int
    actual_cost_usd: float | None = None
    max_cost_usd: float | None = None
    cost_channel: str = "cassette_unmeasured"


@dataclass(frozen=True)
class ContextRatioBudget:
    """Parent→child **size** ceiling (W7.1) — regression guard only.

    Isolation proof is the handoff allow-list (ADR-0009 / ADR-0011), not this ratio.
    """

    parent_role: str
    child_role: str
    actual_context_ratio: float
    max_context_ratio: float


def load_behavioral_baseline() -> dict[str, Any]:
    payload = json.loads(_BASELINE_PATH.read_text(encoding="utf-8"))
    if not isinstance(payload, dict) or "routes" not in payload:
        msg = "behavioral.json must contain routes"
        raise ValueError(msg)
    version = int(payload.get("schema_version", 0))
    if version < 3:
        msg = "behavioral.json schema_version must be >= 3 (W7–W8)"
        raise ValueError(msg)
    return payload


def refresh_policy() -> dict[str, Any]:
    """Baseline refresh contract — required marker + rationale (ADR-0010)."""
    payload = load_behavioral_baseline()
    policy = payload.get("refresh_policy")
    if not isinstance(policy, dict) or not str(policy.get("marker") or "").strip():
        msg = "behavioral.json missing refresh_policy.marker"
        raise ValueError(msg)
    return policy


def _integer(raw: dict[str, Any], key: str, *, fallback_key: str | None = None) -> int:
    """Integer baseline field; a missing/non-integer value is a baseline bug, not a default."""
    value = raw.get(key)
    if value is None and fallback_key is not None:
        value = raw.get(fallback_key)
    if isinstance(value, bool) or not isinstance(value, int):
        msg = f"behavioral.json {key} must be an integer, got {value!r}"
        raise ValueError(msg)
    return value


def _number(raw: dict[str, Any], key: str, *, fallback_key: str | None = None) -> float:
    """Numeric baseline field (int or float). ``None`` stays a caller-level decision."""
    value = raw.get(key)
    if value is None and fallback_key is not None:
        value = raw.get(fallback_key)
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        msg = f"behavioral.json {key} must be numeric, got {value!r}"
        raise ValueError(msg)
    return float(value)


def route_budget(route_id: str) -> RouteBudget:
    payload = load_behavioral_baseline()
    routes = payload["routes"]
    raw = routes.get(route_id)
    if not isinstance(raw, dict):
        msg = f"missing behavioral baseline route: {route_id}"
        raise KeyError(msg)
    actual_steps = _integer(raw, "actual_steps", fallback_key="max_steps")
    actual_handoffs = _integer(raw, "actual_handoffs", fallback_key="max_handoffs")
    channel = str(raw.get("cost_channel") or "cassette_unmeasured")
    raw_actual_cost = raw.get("actual_cost_usd", raw.get("max_cost_usd"))
    raw_max_cost = raw.get("max_cost_usd")
    # None costs are unmeasured — never float(None); cassette channel forces None≠0.
    if channel == "cassette_unmeasured" or raw_actual_cost is None or raw_max_cost is None:
        actual_cost: float | None = None
        max_cost: float | None = None
        channel = "cassette_unmeasured"
    else:
        actual_cost = _number(raw, "actual_cost_usd", fallback_key="max_cost_usd")
        max_cost = _number(raw, "max_cost_usd")
    return RouteBudget(
        actual_steps=actual_steps,
        actual_handoffs=actual_handoffs,
        max_steps=_integer(raw, "max_steps"),
        max_handoffs=_integer(raw, "max_handoffs"),
        max_subagent_depth=_integer(raw, "max_subagent_depth"),
        actual_cost_usd=actual_cost,
        max_cost_usd=max_cost,
        cost_channel=channel,
    )


def context_ratio_budgets() -> tuple[ContextRatioBudget, ...]:
    payload = load_behavioral_baseline()
    raw_map = payload.get("context_ratios") or {}
    if not isinstance(raw_map, dict) or not raw_map:
        msg = "behavioral.json missing context_ratios (v3)"
        raise ValueError(msg)
    rows: list[ContextRatioBudget] = []
    for key, raw in raw_map.items():
        if not isinstance(raw, dict) or "->" not in key:
            continue
        parent, child = key.split("->", 1)
        actual = _number(raw, "actual_context_ratio", fallback_key="max_context_ratio")
        ceiling = _number(raw, "max_context_ratio")
        rows.append(
            ContextRatioBudget(
                parent_role=parent.strip(),
                child_role=child.strip(),
                actual_context_ratio=actual,
                max_context_ratio=ceiling,
            )
        )
    return tuple(rows)


def global_max_subagent_depth() -> int:
    """Nested spawn is forbidden; revision depth ≤ observability.max_quality_revisions."""
    payload = load_behavioral_baseline()
    return int(payload["max_subagent_depth_global"])


def estimated_steps(
    *,
    has_worker: bool,
    revisions: int = 0,
    skip_critic: bool = False,
) -> int:
    """Deterministic step count for the closed LangGraph topology (no nested spawn).

    Counts graph agent/stage nodes, not LLM calls. Prompt edits must not change this.
    """
    steps = _BASE_PIPELINE_STEPS
    if skip_critic:
        steps -= 1
    if has_worker:
        steps += 1
    # Each revision re-enters worker (+ critic) once.
    return steps + max(0, revisions) * 2


__all__ = [
    "ContextRatioBudget",
    "RouteBudget",
    "context_ratio_budgets",
    "estimated_steps",
    "global_max_subagent_depth",
    "load_behavioral_baseline",
    "refresh_policy",
    "route_budget",
]

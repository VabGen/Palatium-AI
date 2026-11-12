# src/palatium_ai/application/agents/evals/product_quality/loader.py

"""Baseline + case loaders for W9 suites (ADR-0012)."""

from __future__ import annotations

import json

from pathlib import Path
from typing import Any

from palatium_ai.application.agents.evals.product_quality.case_schema import (
    ProductQualityCase,
    W9Suite,
)

_PKG = Path(__file__).resolve().parent
_BASELINES = _PKG.parent / "baselines"
_CASES = _PKG / "cases"

_SUITE_FILES: dict[W9Suite, str] = {
    "semantic": "semantic.json",
    "context": "context.json",
    "multi_turn": "multi_turn.json",
    "formatter": "formatter.json",
}


def _pin_rows(payload: dict[str, Any]) -> dict[str, Any]:
    rows = payload.get("agents") or payload.get("request_types") or {}
    if not isinstance(rows, dict) or not rows:
        msg = "baseline missing agents/request_types pins"
        raise ValueError(msg)
    return rows


def _is_zero_placeholder(value: Any) -> bool:
    """``0`` / ``0.0`` as unmeasured stand-in — forbidden (ADR-0012)."""
    if value is None:
        return False
    try:
        return float(value) == 0.0
    except TypeError, ValueError:
        return False


def validate_baseline_pin_row(suite: str, key: str, raw: dict[str, Any]) -> None:
    """Schema for one pin row.

    - Unmeasured: ``measured`` is not true → rates MUST be ``null`` (never ``0.0``).
    - Measured (PR merge / live floor): ``measured: true`` → non-null floats and
      ``actual_pass_rate == min_pass_rate``. ``null`` rates are rejected.
    """
    measured = raw.get("measured") is True
    actual = raw.get("actual_pass_rate")
    minimum = raw.get("min_pass_rate")

    if not measured:
        if actual is not None or minimum is not None:
            if _is_zero_placeholder(actual) or _is_zero_placeholder(minimum):
                msg = (
                    f"{suite}/{key}: 0.0 is not a valid unmeasured placeholder — "
                    "use null rates with measured=false (or omit measured)"
                )
                raise ValueError(msg)
            msg = f"{suite}/{key}: unmeasured pin must use null actual_pass_rate/min_pass_rate (got {actual!r}/{minimum!r})"
            raise ValueError(msg)
        return

    if actual is None or minimum is None:
        msg = f"{suite}/{key}: measured:true rejects null actual_pass_rate/min_pass_rate"
        raise ValueError(msg)
    try:
        actual_f = float(actual)
        minimum_f = float(minimum)
    except (TypeError, ValueError) as exc:
        msg = f"{suite}/{key}: pass rates must be numeric when measured"
        raise ValueError(msg) from exc
    if actual_f != minimum_f:
        msg = f"{suite}/{key}: actual_pass_rate ({actual_f}) != min_pass_rate ({minimum_f})"
        raise ValueError(msg)


def validate_baseline_payload(suite: W9Suite, payload: dict[str, Any]) -> None:
    rows = _pin_rows(payload)
    for key, raw in rows.items():
        if not isinstance(raw, dict):
            msg = f"{suite}/{key}: pin must be object"
            raise TypeError(msg)
        validate_baseline_pin_row(suite, str(key), raw)


def load_suite_baseline(suite: W9Suite) -> dict[str, Any]:
    name = _SUITE_FILES[suite]
    path = _BASELINES / name
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        msg = f"{name} must be an object"
        raise ValueError(msg)
    version = int(payload.get("schema_version", 0))
    if version < 1:
        msg = f"{name} schema_version must be >= 1"
        raise ValueError(msg)
    policy = payload.get("refresh_policy")
    if not isinstance(policy, dict) or str(policy.get("marker") or "").strip() != "[baseline-refresh]":
        msg = f"{name} missing refresh_policy.marker=[baseline-refresh]"
        raise ValueError(msg)
    validate_baseline_payload(suite, payload)
    return payload


def refresh_policy(suite: W9Suite) -> dict[str, Any]:
    payload = load_suite_baseline(suite)
    policy = payload["refresh_policy"]
    if not isinstance(policy, dict):
        msg = f"{suite} refresh_policy must be object"
        raise TypeError(msg)
    return policy


def assert_baseline_pins(suite: W9Suite) -> None:
    """Require at least one ``measured: true`` pin; each measured row has ``actual == min``.

    Unmeasured ``null`` rows may coexist (agents/types not yet covered by cases).
    A baseline with zero measured rows fails — that is not a merge-ready floor.
    """
    payload = load_suite_baseline(suite)
    rows = _pin_rows(payload)
    measured_keys: list[str] = []
    for key, raw in rows.items():
        if not isinstance(raw, dict):
            continue
        if raw.get("measured") is not True:
            continue
        validate_baseline_pin_row(suite, str(key), raw)
        measured_keys.append(str(key))
    if not measured_keys:
        msg = f"{suite}: measured:true required on at least one pin for baseline assert"
        raise ValueError(msg)


def min_pass_rate(suite: W9Suite, *, key: str) -> float:
    payload = load_suite_baseline(suite)
    rows = _pin_rows(payload)
    if key not in rows:
        msg = f"{suite} baseline missing pin for {key!r}"
        raise KeyError(msg)
    raw = rows[key]
    if not isinstance(raw, dict):
        msg = f"{suite}/{key} pin must be object"
        raise TypeError(msg)
    if raw.get("measured") is not True:
        msg = f"{suite}/{key}: min_pass_rate unavailable until measured:true"
        raise ValueError(msg)
    minimum = raw.get("min_pass_rate")
    if minimum is None:
        msg = f"{suite}/{key}: measured pin rejects null min_pass_rate"
        raise ValueError(msg)
    return float(minimum)


def load_cases(suite: W9Suite) -> tuple[ProductQualityCase, ...]:
    suite_dir = _CASES / suite
    if not suite_dir.is_dir():
        msg = f"missing cases directory: {suite_dir}"
        raise FileNotFoundError(msg)
    cases: list[ProductQualityCase] = []
    for path in sorted(suite_dir.glob("*.json")):
        payload = json.loads(path.read_text(encoding="utf-8"))
        rows = payload if isinstance(payload, list) else payload.get("cases")
        if not isinstance(rows, list):
            msg = f"{path.name}: expected list or {{cases: [...]}}"
            raise ValueError(msg)
        cases.extend(ProductQualityCase.from_dict(raw, suite=suite) for raw in rows if isinstance(raw, dict))
    if not cases:
        msg = f"no cases loaded for suite {suite}"
        raise ValueError(msg)
    return tuple(cases)


__all__ = [
    "assert_baseline_pins",
    "load_cases",
    "load_suite_baseline",
    "min_pass_rate",
    "refresh_policy",
    "validate_baseline_payload",
    "validate_baseline_pin_row",
]

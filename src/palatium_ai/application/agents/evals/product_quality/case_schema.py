# src/palatium_ai/application/agents/evals/product_quality/case_schema.py

"""Frozen case contract for W9 suites (ADR-0012)."""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field

W9Agent = Literal["researcher", "analyst", "coder", "formatter"]
W9Suite = Literal["semantic", "context", "multi_turn", "formatter"]
W9Grader = Literal["rule", "rule_then_judge"]


class ProductQualityCase(BaseModel, frozen=True):
    """One live product-quality eval case."""

    id: str = Field(min_length=1, max_length=200)
    suite: W9Suite
    agent: W9Agent
    scenario: str = Field(min_length=1, max_length=200)
    input: dict[str, Any] = Field(default_factory=dict)
    context: dict[str, Any] = Field(default_factory=dict)
    expected: dict[str, Any] = Field(default_factory=dict)
    grader: W9Grader = "rule"
    needs_judge: bool = False
    tags: tuple[str, ...] = ()
    #: Multi-turn only: ordered user turns (assistant replies generated live).
    turns: tuple[dict[str, Any], ...] = ()

    @classmethod
    def from_dict(cls, raw: dict[str, Any], *, suite: W9Suite) -> ProductQualityCase:
        case_id = str(raw.get("id") or "").strip()
        if not case_id:
            msg = "product quality case requires id"
            raise ValueError(msg)
        agent = raw.get("agent")
        if agent not in {"researcher", "analyst", "coder", "formatter"}:
            msg = f"case {case_id}: invalid agent {agent!r}"
            raise ValueError(msg)
        scenario = str(raw.get("scenario") or "").strip()
        if not scenario:
            msg = f"case {case_id}: scenario required"
            raise ValueError(msg)
        expected = raw.get("expected")
        if not isinstance(expected, dict):
            msg = f"case {case_id}: expected must be object"
            raise ValueError(msg)
        grader_raw = raw.get("grader") or ("rule_then_judge" if raw.get("needs_judge") else "rule")
        if grader_raw not in {"rule", "rule_then_judge"}:
            msg = f"case {case_id}: invalid grader {grader_raw!r}"
            raise ValueError(msg)
        tags_raw = raw.get("tags") or []
        tags = tuple(str(t) for t in tags_raw) if isinstance(tags_raw, list) else ()
        turns_raw = raw.get("turns") or []
        turns = tuple(t for t in turns_raw if isinstance(t, dict)) if isinstance(turns_raw, list) else ()
        case_input = raw.get("input")
        case_context = raw.get("context")
        return cls(
            id=case_id,
            suite=suite,
            agent=agent,
            scenario=scenario,
            input=case_input if isinstance(case_input, dict) else {},
            context=case_context if isinstance(case_context, dict) else {},
            expected=expected,
            grader=grader_raw,  # type: ignore[arg-type]
            needs_judge=bool(raw.get("needs_judge", grader_raw == "rule_then_judge")),
            tags=tags,
            turns=turns,
        )


__all__ = ["ProductQualityCase", "W9Agent", "W9Grader", "W9Suite"]

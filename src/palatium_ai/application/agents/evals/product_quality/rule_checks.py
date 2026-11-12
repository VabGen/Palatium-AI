# src/palatium_ai/application/agents/evals/product_quality/rule_checks.py

"""Rule-based graders for W9 — must_contain / must_not_contain / structure (ADR-0012)."""

from __future__ import annotations

import re

from typing import Any

from palatium_ai.domain.agents.evals import GradeResult, failed, passed

_WS = re.compile(r"\s+")


def normalize_text(text: str) -> str:
    """Casefold + collapse whitespace for stable substring checks."""
    return _WS.sub(" ", text.casefold()).strip()


def must_contain(text: str, needles: list[str] | tuple[str, ...]) -> list[str]:
    """Return needles missing from ``text`` (normalized)."""
    hay = normalize_text(text)
    missing: list[str] = []
    for needle in needles:
        n = normalize_text(str(needle))
        if not n:
            continue
        if n not in hay:
            missing.append(str(needle))
    return missing


def must_not_contain(text: str, needles: list[str] | tuple[str, ...]) -> list[str]:
    """Return needles that incorrectly appear in ``text``."""
    hay = normalize_text(text)
    found: list[str] = []
    for needle in needles:
        n = normalize_text(str(needle))
        if not n:
            continue
        if n in hay:
            found.append(str(needle))
    return found


def _has_list_markers(text: str) -> bool:
    lines = text.splitlines()
    bullet = sum(1 for line in lines if re.match(r"^\s*([-*+]|\d+[.)])\s+\S", line))
    return bullet >= 2


def _has_code_fence(text: str) -> bool:
    return "```" in text


def _has_heading(text: str) -> bool:
    return bool(re.search(r"(?m)^#{1,3}\s+\S", text)) or bool(re.search(r"(?m)^.+\n[-=]{3,}\s*$", text))


def _max_paragraph_words(text: str) -> int:
    parts = re.split(r"\n\s*\n", text.strip())
    if not parts:
        return 0
    return max((len(p.split()) for p in parts), default=0)


def grade_structure(text: str, expected: dict[str, Any]) -> GradeResult | None:
    """Optional structure checks for formatter request-types. None = no structure rules."""
    req = expected.get("structure")
    if not isinstance(req, dict) or not req:
        return None
    if req.get("require_list") and not _has_list_markers(text):
        return failed(0.0, details="structure: expected list markers")
    if req.get("require_code_fence") and not _has_code_fence(text):
        return failed(0.0, details="structure: expected fenced code block")
    if req.get("require_heading") and not _has_heading(text):
        return failed(0.0, details="structure: expected heading")
    max_para = req.get("max_paragraph_words")
    if isinstance(max_para, int) and max_para > 0:
        words = _max_paragraph_words(text)
        if words > max_para and not _has_list_markers(text):
            return failed(0.0, details=f"structure: wall-of-text paragraph ({words}>{max_para})")
    return None


def grade_field_preservation(text: str, expected: dict[str, Any]) -> GradeResult | None:
    """Upstream fields must survive formatting."""
    fields = expected.get("preserve_fields")
    if not isinstance(fields, dict) or not fields:
        return None
    missing = must_contain(text, [str(v) for v in fields.values() if str(v).strip()])
    if missing:
        return failed(0.0, details=f"preserve_fields missing: {missing}")
    return None


def grade_rules(text: str, expected: dict[str, Any]) -> GradeResult:
    """Rule-first gate: contain / not-contain / structure / field preservation."""
    if not isinstance(expected, dict):
        return failed(0.0, details="expected must be an object")

    contain = expected.get("must_contain") or []
    forbid = expected.get("must_not_contain") or []
    if not isinstance(contain, list) or not isinstance(forbid, list):
        return failed(0.0, details="must_contain/must_not_contain must be lists")

    missing = must_contain(text, [str(x) for x in contain])
    if missing:
        return failed(0.0, details=f"must_contain missing: {missing}")

    leaked = must_not_contain(text, [str(x) for x in forbid])
    if leaked:
        return failed(0.0, details=f"must_not_contain hit: {leaked}")

    structured = grade_structure(text, expected)
    if structured is not None and not structured.passed:
        return structured

    preserved = grade_field_preservation(text, expected)
    if preserved is not None and not preserved.passed:
        return preserved

    return passed(1.0, details="rule checks ok")


__all__ = [
    "grade_field_preservation",
    "grade_rules",
    "grade_structure",
    "must_contain",
    "must_not_contain",
    "normalize_text",
]

# src/palatium_ai/application/agents/evals/conflict_linter/static_rules.py

"""Same-prompt static heuristics (v1 — low FP; cross-prompt deferred)."""

from __future__ import annotations

import re

from typing import Final

from palatium_ai.application.agents.evals.conflict_linter.models import ConflictFinding
from palatium_ai.application.agents.evals.conflict_linter.sections import PromptSection

# Polarity lexicons — word-boundary; English prompt language (project SoT).
_BRIEF: Final[re.Pattern[str]] = re.compile(
    r"\b(brief(?:ly)?|concise|short(?:en)?|terse|minimal(?:ly)?)\b",
    re.IGNORECASE,
)
_DETAILED: Final[re.Pattern[str]] = re.compile(
    r"\b(detailed|exhaustive|comprehensive|verbose|expand(?:ed|ing)?|thorough)\b",
    re.IGNORECASE,
)
_ALWAYS: Final[re.Pattern[str]] = re.compile(r"\balways\b", re.IGNORECASE)
_NEVER: Final[re.Pattern[str]] = re.compile(r"\bnever\b", re.IGNORECASE)
_MUST: Final[re.Pattern[str]] = re.compile(r"\bmust\b", re.IGNORECASE)
_MAY: Final[re.Pattern[str]] = re.compile(r"\bmay\b", re.IGNORECASE)

#: Security / fence prose uses "never follow" intentionally — not an always/never conflict.
_SECURITY_NEVER: Final[re.Pattern[str]] = re.compile(
    r"\bnever\b.{0,40}\b(follow|obey|execute|trust)\b"
    r"|\b(follow|obey|execute)\b.{0,40}\bnever\b"
    r"|\buntrusted\b|\bfence\b|\binjection\b",
    re.IGNORECASE | re.DOTALL,
)

#: Length budget as a *parameter* (verbosity_budget / shorten|expand axis) is not a prose conflict.
_AXIS_CONTEXT: Final[re.Pattern[str]] = re.compile(
    r"verbosity_budget|transformation|shorten|expand\s+ask|style_hint|text\.verbosity",
    re.IGNORECASE,
)


def _first_match(pattern: re.Pattern[str], text: str) -> str | None:
    match = pattern.search(text)
    return match.group(0) if match else None


def scan_section(
    section: PromptSection,
    *,
    path: str,
    prompt_id: str | None,
    line_base: int,
) -> list[ConflictFinding]:
    """Flag antonym / modality clashes inside one ``#`` section only."""
    body = section.body
    if not body.strip():
        return []

    findings: list[ConflictFinding] = []
    line_hint = line_base + section.start_line - 1

    if not _AXIS_CONTEXT.search(body):
        left = _first_match(_BRIEF, body)
        right = _first_match(_DETAILED, body)
        if left and right:
            findings.append(
                ConflictFinding(
                    path=path,
                    prompt_id=prompt_id,
                    severity="hard",
                    kind="antonym_pair",
                    section=section.title,
                    message="brief/concise polarity vs detailed/expand in the same section",
                    left=left,
                    right=right,
                    line_hint=line_hint,
                )
            )

    always = _first_match(_ALWAYS, body)
    never = _first_match(_NEVER, body)
    if always and never and not _SECURITY_NEVER.search(body):
        findings.append(
            ConflictFinding(
                path=path,
                prompt_id=prompt_id,
                severity="hard",
                kind="always_never",
                section=section.title,
                message="always vs never in the same section (non-security)",
                left=always,
                right=never,
                line_hint=line_hint,
            )
        )

    must = _first_match(_MUST, body)
    may = _first_match(_MAY, body)
    # "may" is common English — keep soft to avoid drowning triage.
    if must and may:
        findings.append(
            ConflictFinding(
                path=path,
                prompt_id=prompt_id,
                severity="soft",
                kind="must_may",
                section=section.title,
                message="must vs may in the same section",
                left=must,
                right=may,
                line_hint=line_hint,
            )
        )

    return findings

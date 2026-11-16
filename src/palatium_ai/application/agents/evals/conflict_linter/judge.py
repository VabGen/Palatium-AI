# src/palatium_ai/application/agents/evals/conflict_linter/judge.py

"""Sampled conflict judge (v1: deterministic heuristic; optional LLM later).

PR CI must not depend on vendor keys. The heuristic judge encodes the same
few-shot shape an LLM judge would use on the fixture set; swap in LiteLLM
behind ``--judge llm`` when ``PALATIUM_CONFLICT_JUDGE=1``.
"""

from __future__ import annotations

import re

from typing import Protocol

from palatium_ai.application.agents.evals.conflict_linter.models import ConflictFinding


class ConflictJudge(Protocol):
    def judge(self, text: str, *, path: str, prompt_id: str | None) -> list[ConflictFinding]:
        """Return semantic findings (hard/soft) for one prompt body."""
        ...


_CLARIFY_ALWAYS = re.compile(
    r"\b(always|must)\b.{0,60}\bclarif(?:y|ication)\b|\bclarif(?:y|ication)\b.{0,60}\b(always|every)\b",
    re.IGNORECASE | re.DOTALL,
)
_CLARIFY_NEVER = re.compile(
    r"\b(never|avoid|do not|don't)\b.{0,60}\bclarif(?:y|ication)\b"
    r"|\bfalse\s+clarification\b",
    re.IGNORECASE | re.DOTALL,
)
_JSON_ONLY = re.compile(r"\b(json\s+only|only\s+valid\s+json|return\s+only\s+json)\b", re.IGNORECASE)
_PROSE_ONLY = re.compile(
    r"\b(free-?form\s+prose\s+only|never\s+json|plain\s+prose\s+only)\b",
    re.IGNORECASE,
)


class HeuristicJudge:
    """Fixture-oriented semantic layer (stand-in until live LLM judge is wired)."""

    def judge(self, text: str, *, path: str, prompt_id: str | None) -> list[ConflictFinding]:
        findings: list[ConflictFinding] = []
        if _CLARIFY_ALWAYS.search(text) and _CLARIFY_NEVER.search(text):
            findings.append(
                ConflictFinding(
                    path=path,
                    prompt_id=prompt_id,
                    severity="hard",
                    kind="semantic_judge",
                    section="(whole)",
                    message="clarify-always vs avoid/false-clarification in one prompt",
                    left="clarify-required",
                    right="clarify-forbidden",
                )
            )
        if _JSON_ONLY.search(text) and _PROSE_ONLY.search(text):
            findings.append(
                ConflictFinding(
                    path=path,
                    prompt_id=prompt_id,
                    severity="hard",
                    kind="semantic_judge",
                    section="(whole)",
                    message="JSON-only vs prose-only output contract",
                    left="json-only",
                    right="prose-only",
                )
            )
        return findings

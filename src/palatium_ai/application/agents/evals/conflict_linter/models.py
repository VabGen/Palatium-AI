# src/palatium_ai/application/agents/evals/conflict_linter/models.py

"""Conflict-linter findings (prompt-audit backlog §2)."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field

ConflictSeverity = Literal["hard", "soft"]
ConflictKind = Literal[
    "antonym_pair",
    "always_never",
    "must_may",
    "semantic_judge",
]


class ConflictFinding(BaseModel, frozen=True):
    """One suspected instruction conflict inside a same-prompt scan."""

    path: str
    prompt_id: str | None = None
    severity: ConflictSeverity
    kind: ConflictKind
    section: str
    message: str
    left: str
    right: str
    line_hint: int | None = None
    suppressed: bool = False
    noqa_reason: str | None = None


class ConflictReport(BaseModel, frozen=True):
    """Aggregated scan / fixture run."""

    findings: tuple[ConflictFinding, ...] = ()
    scanned_files: int = 0
    mode: Literal["same_prompt"] = "same_prompt"

    @property
    def active(self) -> tuple[ConflictFinding, ...]:
        return tuple(item for item in self.findings if not item.suppressed)

    @property
    def hard_count(self) -> int:
        return sum(1 for item in self.active if item.severity == "hard")


class FixtureCase(BaseModel, frozen=True):
    """Golden conflict / non-conflict snippet for regression."""

    fixture_id: str = Field(min_length=1)
    expected: Literal["conflict", "non_conflict"]
    relative_path: str = Field(min_length=1)
    note: str = ""

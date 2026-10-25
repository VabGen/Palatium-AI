# src/palatium_ai/domain/content/lint/models.py

"""Typed result of the deterministic ``ContentDocument`` lint (W0a, 040/050).

The lint is a *measurement* layer: it never rewrites the document. Repair stays in
the formatter pipeline, where a second source of content edits would otherwise
appear (050: one owner per decision).
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel

#: Closed set: a new rule is added here, in ``rules.py`` and in the metric registry
#: together. The label set is what keeps ``palatium_content_lint_findings_total``
#: cardinality bounded (040).
LintRuleId = Literal[
    "internal_marker_leak",
    "dangling_citation",
    "duplicate_prose",
    "markdown_residue",
    "empty_section",
]

LintSeverity = Literal["error", "warning"]


class LintFinding(BaseModel, frozen=True):
    """One rule hit. No prose is stored: findings go to logs/metrics only (020)."""

    rule_id: LintRuleId
    severity: LintSeverity
    #: Position in ``ContentDocument.blocks``; ``None`` when the defect is document-wide.
    block_index: int | None = None


class LintReport(BaseModel, frozen=True):
    """All findings of one document, in rule order (deterministic)."""

    findings: tuple[LintFinding, ...] = ()

    @property
    def error_count(self) -> int:
        return sum(1 for finding in self.findings if finding.severity == "error")


__all__ = ["LintFinding", "LintReport", "LintRuleId", "LintSeverity"]

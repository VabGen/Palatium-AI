# src/palatium_ai/domain/content/lint/engine.py

"""Single entry point of the deterministic ContentDocument lint (W0a)."""

from __future__ import annotations

from palatium_ai.domain.content.content_document import ContentDocument
from palatium_ai.domain.content.lint.models import LintFinding, LintReport
from palatium_ai.domain.content.lint.rules import RULES, prose_items


class ContentLint:
    """Run the closed rule set once per document; never mutates the document."""

    @classmethod
    def run(cls, document: ContentDocument) -> LintReport:
        prose = prose_items(document)
        findings: list[LintFinding] = []
        for rule in RULES:
            findings.extend(rule.check(document, prose))
        return LintReport(findings=tuple(findings))


__all__ = ["ContentLint"]

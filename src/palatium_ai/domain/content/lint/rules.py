# src/palatium_ai/domain/content/lint/rules.py

"""Deterministic ContentDocument rules (W0a).

Rules are pure functions over a validated document: no LLM, no I/O, no phrase
lists (055). They answer a different question from Pydantic — "is a *valid*
document also a *correct* one for the user?" — so they run after parsing, not
instead of it.

Two checks are deliberately absent:

* **shape compliance** — owned by ``ShapeRecipePolicy`` (a second copy would be a
  second source of truth, 050);
* **internal vocabulary rewriting** — owned by ``InternalVocabularyPolicy``. The
  lint only *detects* what the sanitizer should already have removed; a hit means
  the guard has a gap, which is exactly the signal we want.
"""

from __future__ import annotations

import re

from collections import defaultdict
from typing import TYPE_CHECKING, ClassVar, Protocol

from palatium_ai.domain.content.content_document import (
    CalloutBlock,
    ChartBlock,
    CodeBlock,
    DividerBlock,
    FormulaBlock,
    HeadingBlock,
    KeyValueBlock,
    ListBlock,
    ParagraphBlock,
    StepsBlock,
    TableBlock,
    WidgetBlock,
)
from palatium_ai.domain.content.lint.models import (
    LintFinding,
    LintRuleId,
    LintSeverity,
)
from palatium_ai.domain.policies.internal_vocabulary import InternalVocabularyPolicy

if TYPE_CHECKING:
    from palatium_ai.domain.content.content_document import ContentBlock, ContentDocument

#: Our own notation printed as content (040: bounded, not a phrase list).
_INTERNAL_MARKER_RE = re.compile(r"\[\[page \d+\]\]|\bmcp:[A-Za-z0-9_]+\.[A-Za-z0-9_]+")
#: ``[1]``-style citation markers the answer uses to point at ``meta.source_refs``.
_CITATION_MARKER_RE = re.compile(r"\[(\d{1,2})\]")
#: Markdown that survived into a plain-text block: the document was parsed twice or
#: the cleanup missed a line. A paragraph is not a container for its own syntax.
_MARKDOWN_RESIDUE_RE = re.compile(r"^(?:#{1,6}\s|```|\||>|[-*+]\s|\d{1,3}\.\s)")
_WHITESPACE_RUN_RE = re.compile(r"\s+")


class Rule(Protocol):
    """One deterministic check; the engine runs the closed tuple once per document."""

    rule_id: ClassVar[LintRuleId]
    severity: ClassVar[LintSeverity]

    def check(
        self,
        document: ContentDocument,
        prose: tuple[tuple[int, str], ...],
    ) -> list[LintFinding]: ...


class InternalMarkerLeak:
    """Internal field names / page markers / MCP ids visible to the user."""

    rule_id: ClassVar[LintRuleId] = "internal_marker_leak"
    severity: ClassVar[LintSeverity] = "error"

    def check(
        self,
        document: ContentDocument,
        prose: tuple[tuple[int, str], ...],
    ) -> list[LintFinding]:
        return [
            LintFinding(rule_id=self.rule_id, severity=self.severity, block_index=index)
            for index, text in prose
            if InternalVocabularyPolicy.has_terms(text) or _INTERNAL_MARKER_RE.search(text)
        ]


class DanglingCitation:
    """``[n]`` without the source it points at is a broken promise, not a style nit."""

    rule_id: ClassVar[LintRuleId] = "dangling_citation"
    severity: ClassVar[LintSeverity] = "error"

    def check(
        self,
        document: ContentDocument,
        prose: tuple[tuple[int, str], ...],
    ) -> list[LintFinding]:
        source_count = len(document.meta.source_refs)
        for index, text in prose:
            for match in _CITATION_MARKER_RE.finditer(text):
                number = int(match.group(1))
                if number < 1 or number > source_count:
                    return [
                        LintFinding(rule_id=self.rule_id, severity=self.severity, block_index=index),
                    ]
        return []


class DuplicateProse:
    """Two adjacent blocks with the same text — the model looped, the user sees it twice."""

    rule_id: ClassVar[LintRuleId] = "duplicate_prose"
    severity: ClassVar[LintSeverity] = "warning"

    def check(
        self,
        document: ContentDocument,
        prose: tuple[tuple[int, str], ...],
    ) -> list[LintFinding]:
        by_block: dict[int, list[str]] = defaultdict(list)
        for index, text in prose:
            normalized = _normalize(text)
            if normalized:
                by_block[index].append(normalized)

        findings: list[LintFinding] = []
        previous_index: int | None = None
        previous_text = ""
        for index in sorted(by_block):
            text = " ".join(by_block[index])
            if previous_index is not None and index == previous_index + 1 and text == previous_text:
                findings.append(
                    LintFinding(rule_id=self.rule_id, severity=self.severity, block_index=index),
                )
            previous_index = index
            previous_text = text
        return findings


class MarkdownResidue:
    """Markdown syntax inside a typed block means the answer was parsed twice."""

    rule_id: ClassVar[LintRuleId] = "markdown_residue"
    severity: ClassVar[LintSeverity] = "error"

    def check(
        self,
        document: ContentDocument,
        prose: tuple[tuple[int, str], ...],
    ) -> list[LintFinding]:
        # Table cells / kv values are excluded on purpose: "1. Пункт" is a legitimate
        # cell, while the same prefix in a paragraph is a list that leaked through.
        return [
            LintFinding(rule_id=self.rule_id, severity=self.severity, block_index=index)
            for index, block in enumerate(document.blocks)
            for text in _markdown_capable_text(block)
            if _MARKDOWN_RESIDUE_RE.match(text.strip())
        ]


class EmptySection:
    """A heading with no body (next block is a heading, divider, or end of document)."""

    rule_id: ClassVar[LintRuleId] = "empty_section"
    severity: ClassVar[LintSeverity] = "warning"

    def check(
        self,
        document: ContentDocument,
        prose: tuple[tuple[int, str], ...],
    ) -> list[LintFinding]:
        findings: list[LintFinding] = []
        blocks = document.blocks
        for index, block in enumerate(blocks):
            if not isinstance(block, HeadingBlock):
                continue
            following = blocks[index + 1] if index + 1 < len(blocks) else None
            if following is None or isinstance(following, HeadingBlock | DividerBlock):
                findings.append(
                    LintFinding(rule_id=self.rule_id, severity=self.severity, block_index=index),
                )
        return findings


RULES: tuple[Rule, ...] = (
    InternalMarkerLeak(),
    DanglingCitation(),
    DuplicateProse(),
    MarkdownResidue(),
    EmptySection(),
)


def prose_items(document: ContentDocument) -> tuple[tuple[int, str], ...]:
    """User-visible prose per block index.

    ``code``/``formula`` bodies are the user's own text and are never checked: the
    internal-vocabulary sanitizer skips them for the same reason (055).
    """
    return tuple((index, text) for index, block in enumerate(document.blocks) for text in _block_prose(block))


def _block_prose(block: ContentBlock) -> tuple[str, ...]:
    match block:
        case HeadingBlock(text=text) | ParagraphBlock(text=text):
            return (text,)
        case CalloutBlock(title=title, body=body):
            return (*((title,) if title else ()), body)
        case ListBlock(items=items):
            return tuple(part for item in items for part in (item.text, *((item.emphasis,) if item.emphasis else ())))
        case TableBlock(columns=columns, rows=rows):
            return (*columns, *(cell for row in rows for cell in row))
        case KeyValueBlock(items=items):
            return tuple(part for item in items for part in (item.label, item.value))
        case StepsBlock(items=items):
            return tuple(part for item in items for part in (item.title, item.body))
        case ChartBlock(title=title, labels=labels, series=series):
            names = tuple(series_item.name for series_item in series)
            return (*((title,) if title else ()), *labels, *names)
        case WidgetBlock(title=title):
            return (title,) if title else ()
        case CodeBlock() | FormulaBlock() | DividerBlock():
            return ()


def _markdown_capable_text(block: ContentBlock) -> tuple[str, ...]:
    """Plain-text blocks where leading markdown is always a parsing residue."""
    match block:
        case HeadingBlock(text=text) | ParagraphBlock(text=text):
            return (text,)
        case CalloutBlock(title=title, body=body):
            return (*((title,) if title else ()), body)
        case ListBlock(items=items):
            return tuple(item.text for item in items)
        case StepsBlock(items=items):
            return tuple(part for item in items for part in (item.title, item.body))
        case _:
            return ()


def _normalize(text: str) -> str:
    return _WHITESPACE_RUN_RE.sub(" ", text).strip().casefold()


__all__ = [
    "RULES",
    "DanglingCitation",
    "DuplicateProse",
    "EmptySection",
    "InternalMarkerLeak",
    "MarkdownResidue",
    "Rule",
    "prose_items",
]

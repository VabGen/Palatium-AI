# src/palatium_ai/domain/content/citations/markers.py

"""Drop ``[n]`` markers that only duplicate ``meta.source_refs`` (pure, no I/O).

Sources travel as structured data and the client renders them as a footer. A ``[1]``
left in the prose is therefore not a citation the user can follow — it is punctuation
the model kept from its drafting, and it renders as a bare artifact (issue: ответы с
``[1]`` после абзаца).

The rule is deliberately narrow in one direction: a marker is removed **only** when a
source with that number exists. A marker pointing at a source we do not have is a
broken promise; swallowing it would hide the defect, so it is left for the
``dangling_citation`` lint rule to report and the repair pass to fix.
"""

from __future__ import annotations

import re

from palatium_ai.domain.content.content_document import (
    CalloutBlock,
    ContentBlock,
    ContentDocument,
    HeadingBlock,
    KeyValueBlock,
    ListBlock,
    ListItem,
    ParagraphBlock,
    StepsBlock,
    TableBlock,
)

#: ``[12]`` not followed by ``(`` — a markdown link ``[1](url)`` is a real control.
_MARKER_RE = re.compile(r"[ \t]*\[(\d{1,2})\](?!\()")
#: Collapsing runs keeps the sentence readable after an inline marker disappears.
_SPACE_RUN_RE = re.compile(r"[ \t]{2,}")

__all__ = ["strip_citation_markers"]


def strip_citation_markers(document: ContentDocument, *, source_count: int) -> ContentDocument:
    """Remove ``[1..source_count]`` markers from user-facing prose blocks."""
    if source_count <= 0:
        return document
    cleaned = tuple(block for block in (_clean_block(block, source_count) for block in document.blocks) if block is not None)
    if cleaned == document.blocks:
        return document
    return document.model_copy(update={"blocks": cleaned})


def _clean_block(block: ContentBlock, source_count: int) -> ContentBlock | None:
    """Cleaned copy of one block; ``None`` when nothing readable is left of it."""
    match block:
        case HeadingBlock(text=text):
            return _with_text(block, text, source_count)
        case ParagraphBlock(text=text):
            return _with_text(block, text, source_count)
        case CalloutBlock(body=body):
            new_body = _clean_text(body, source_count)
            if not new_body:
                return None
            title = _clean_text(block.title, source_count) if block.title else None
            return block.model_copy(update={"body": new_body, "title": title or None})
        case ListBlock(items=items):
            rows = tuple(row for row in (_clean_item(item, source_count) for item in items) if row is not None)
            return block.model_copy(update={"items": rows}) if rows else None
        case TableBlock(columns=columns, rows=rows):
            return block.model_copy(
                update={
                    "columns": tuple(_clean_text(cell, source_count) for cell in columns),
                    "rows": tuple(tuple(_clean_text(cell, source_count) for cell in row) for row in rows),
                }
            )
        case StepsBlock(items=items):
            steps = tuple(
                step
                for step in (
                    step.model_copy(
                        update={
                            "title": _clean_text(step.title, source_count),
                            "body": _clean_text(step.body, source_count),
                        }
                    )
                    for step in items
                )
                if step.title
            )
            return block.model_copy(update={"items": steps}) if steps else None
        case KeyValueBlock(items=items):
            pairs = tuple(
                pair
                for pair in (
                    pair.model_copy(
                        update={
                            "label": _clean_text(pair.label, source_count),
                            "value": _clean_text(pair.value, source_count),
                        }
                    )
                    for pair in items
                )
                if pair.label and pair.value
            )
            return block.model_copy(update={"items": pairs}) if pairs else None
        case _:
            # Code, formula, chart, divider, widget carry verbatim / structured payloads.
            return block


def _with_text(block: HeadingBlock | ParagraphBlock, text: str, source_count: int) -> ContentBlock | None:
    cleaned = _clean_text(text, source_count)
    return block.model_copy(update={"text": cleaned}) if cleaned else None


def _clean_item(item: ListItem, source_count: int) -> ListItem | None:
    text = _clean_text(item.text, source_count)
    if not text:
        return None
    emphasis = _clean_text(item.emphasis, source_count) if item.emphasis else None
    return item.model_copy(update={"text": text, "emphasis": emphasis or None})


def _clean_text(text: str, source_count: int) -> str:
    """Strip known markers, then re-collapse the spaces they left behind."""

    def _replace(match: re.Match[str]) -> str:
        number = int(match.group(1))
        return "" if 1 <= number <= source_count else match.group(0)

    cleaned = _MARKER_RE.sub(_replace, text)
    return _SPACE_RUN_RE.sub(" ", cleaned).strip()

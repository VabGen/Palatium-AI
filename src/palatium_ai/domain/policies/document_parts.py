# src/palatium_ai/domain/policies/document_parts.py

"""Admit text attachments as citeable ``DocumentPart``s (W3a grounding input).

Pure policy over already-fenced turn blocks: no I/O. Titles match
``citation_refs_from_untrusted_context`` so provider ``document_title`` resolves to
the same chip label the UI shows.
"""

from __future__ import annotations

import re

from collections import defaultdict

from palatium_ai.domain.attachments.context import AttachmentContextBlock
from palatium_ai.domain.llm.models import DocumentPart

_FENCE_BODY = re.compile(
    r"<<<UNTRUSTED_TOOL_OUTPUT\s+source=[^\s>]+>>>\n(?P<body>.*?)\n<<<END_UNTRUSTED_TOOL_OUTPUT>>>",
    re.DOTALL,
)
_MAX_PARTS = 8
_MAX_CHARS_PER_PART = 48_000


def document_parts_from_blocks(blocks: tuple[AttachmentContextBlock, ...] | list[AttachmentContextBlock]) -> tuple[DocumentPart, ...]:
    """Build citeable parts for non-image blocks that already carry extracted text."""
    usable = [block for block in blocks if block.has_usable_text and not block.is_image]
    if not usable:
        return ()

    ids_by_name: dict[str, set[str]] = defaultdict(set)
    for block in usable:
        ids_by_name[block.filename].add(str(block.attachment_id))

    parts: list[DocumentPart] = []
    for block in usable:
        body = _fence_body(block.fenced_text)
        if not body:
            continue
        id8 = str(block.attachment_id).replace("-", "")[:8]
        needs_id = len(ids_by_name[block.filename]) > 1
        title = f"{block.filename}#{id8}" if needs_id and id8 else block.filename
        parts.append(
            DocumentPart(
                attachment_id=block.attachment_id,
                title=title[:255],
                text=body[:_MAX_CHARS_PER_PART],
            )
        )
        if len(parts) >= _MAX_PARTS:
            break
    return tuple(parts)


def _fence_body(fenced: str) -> str:
    match = _FENCE_BODY.search(fenced or "")
    if match is None:
        return (fenced or "").strip()
    return match.group("body").strip()


__all__ = ["document_parts_from_blocks"]

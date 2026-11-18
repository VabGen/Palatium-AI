"""document_parts must rebuild from post-selection blocks (Context Circulation)."""

from __future__ import annotations

from uuid import uuid4

from palatium_ai.domain.attachments.context import AttachmentContextBlock
from palatium_ai.domain.policies.document_parts import document_parts_from_blocks


def _block(name: str, body: str) -> AttachmentContextBlock:
    aid = uuid4()
    source = f"attachment:{aid}:{name}"
    fence = f"<<<UNTRUSTED_TOOL_OUTPUT source={source}>>>\n{body}\n<<<END_UNTRUSTED_TOOL_OUTPUT>>>"
    return AttachmentContextBlock(
        attachment_id=aid,
        filename=name,
        source=source,
        fenced_text=fence,
        action="allow",
        mime_type="application/pdf",
        text_state="extracted",
    )


def test_rebuild_keeps_only_selected_usable_blocks() -> None:
    selected = (_block("a.pdf", "Alpha body"), _block("b.pdf", "Beta body"))
    parts = document_parts_from_blocks(selected)
    assert len(parts) == 2
    titles = {part.title for part in parts}
    assert "a.pdf" in titles
    assert "b.pdf" in titles

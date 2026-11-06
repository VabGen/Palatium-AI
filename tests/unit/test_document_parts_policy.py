"""Admit text attachments as citeable DocumentPart (W3a)."""

from __future__ import annotations

from uuid import UUID

from palatium_ai.domain.attachments.context import AttachmentContextBlock
from palatium_ai.domain.memory.tool_output import wrap_untrusted_tool_output
from palatium_ai.domain.policies.document_parts import document_parts_from_blocks

_ID_A = UUID("aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa")
_ID_B = UUID("bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb")


def _block(
    *,
    attachment_id: UUID,
    filename: str,
    body: str,
    mime_type: str = "application/pdf",
    text_state: str = "extracted",
) -> AttachmentContextBlock:
    return AttachmentContextBlock(
        attachment_id=attachment_id,
        filename=filename,
        source=f"attachment:{filename}",
        fenced_text=wrap_untrusted_tool_output(body, source=f"attachment:{filename}"),
        action="allow",
        mime_type=mime_type,
        text_state=text_state,  # type: ignore[arg-type]
    )


def test_document_parts_skip_images_and_missing_text() -> None:
    parts = document_parts_from_blocks(
        (
            _block(attachment_id=_ID_A, filename="photo.png", body="pixels", mime_type="image/png"),
            _block(
                attachment_id=_ID_B,
                filename="empty.pdf",
                body="",
                text_state="missing",
            ),
        )
    )
    assert parts == ()


def test_document_parts_title_matches_citation_chip() -> None:
    parts = document_parts_from_blocks(
        (_block(attachment_id=_ID_A, filename="report.pdf", body="Clause 1. Payment terms."),)
    )
    assert len(parts) == 1
    assert parts[0].title == "report.pdf"
    assert parts[0].attachment_id == _ID_A
    assert "Payment terms" in parts[0].text
    assert "<<<UNTRUSTED" not in parts[0].text


def test_same_filename_two_ids_disambiguate_title() -> None:
    name = "policy.docx"
    parts = document_parts_from_blocks(
        (
            _block(attachment_id=_ID_A, filename=name, body="version A"),
            _block(attachment_id=_ID_B, filename=name, body="version B"),
        )
    )
    assert len(parts) == 2
    assert parts[0].title != parts[1].title
    assert "aaaaaaaa" in parts[0].title
    assert "bbbbbbbb" in parts[1].title

# tests/unit/test_attachment_fence_source.py

"""Unique attachment fence sources for same-named uploads."""

from __future__ import annotations

from uuid import UUID

from palatium_ai.domain.attachments.fence_source import attachment_fence_source

_ID = UUID("12345678-1234-4234-8234-123456789abc")


def test_fence_source_includes_id_and_filename() -> None:
    source = attachment_fence_source(attachment_id=_ID, filename="report.pdf")
    assert source == f"attachment:{_ID}:report.pdf"


def test_same_name_different_ids() -> None:
    a = attachment_fence_source(attachment_id=_ID, filename="Kodex.docx")
    b = attachment_fence_source(
        attachment_id=UUID("aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa"),
        filename="Kodex.docx",
    )
    assert a != b
    assert a.endswith(":Kodex.docx")
    assert b.endswith(":Kodex.docx")


def test_fence_source_respects_cap() -> None:
    long_name = "x" * 200 + ".docx"
    source = attachment_fence_source(attachment_id=_ID, filename=long_name)
    assert len(source) <= 128
    assert source.startswith(f"attachment:{_ID}:")
    assert source.endswith(".docx")

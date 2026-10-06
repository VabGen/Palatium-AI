# tests/unit/test_attachment_citations.py

"""Attachment file citation labels from fenced turn context (W2 G03)."""

from __future__ import annotations

from uuid import UUID

from palatium_ai.domain.attachments.citations import (
    citation_refs_from_untrusted_context,
    sanitize_source_refs,
)
from palatium_ai.domain.attachments.fence_source import attachment_fence_source
from palatium_ai.domain.memory.tool_output import wrap_untrusted_tool_output

_ID_A = UUID("aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa")
_ID_B = UUID("bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb")


def test_citations_are_filename_only_even_with_pages() -> None:
    """Page markers must not become extra UI chips (hash#pN noise)."""
    body = "[[page 1]]\nHello\n[[page 2]]\nWorld"
    source = attachment_fence_source(attachment_id=_ID_A, filename="report.pdf")
    fenced = wrap_untrusted_tool_output(body, source=source)
    assert citation_refs_from_untrusted_context(fenced) == ("report.pdf",)


def test_citations_long_pdf_still_one_filename_chip() -> None:
    pages = "\n".join(f"[[page {n}]]\nchunk {n}" for n in range(1, 33))
    source = attachment_fence_source(attachment_id=_ID_A, filename="СФОТ_Банки.pdf")
    fenced = wrap_untrusted_tool_output(pages, source=source)
    assert citation_refs_from_untrusted_context(fenced) == ("СФОТ_Банки.pdf",)


def test_citations_filename_only_without_pages() -> None:
    source = attachment_fence_source(attachment_id=_ID_A, filename="note.txt")
    fenced = wrap_untrusted_tool_output("plain note", source=source)
    assert citation_refs_from_untrusted_context(fenced) == ("note.txt",)


def test_same_filename_two_ids_stay_distinct() -> None:
    name = "Кодекс_корпоративной_этики_V2.docx"
    a = wrap_untrusted_tool_output(
        "version A body",
        source=attachment_fence_source(attachment_id=_ID_A, filename=name),
    )
    b = wrap_untrusted_tool_output(
        "version B body",
        source=attachment_fence_source(attachment_id=_ID_B, filename=name),
    )
    refs = citation_refs_from_untrusted_context(f"{a}\n\n{b}")
    assert len(refs) == 2
    assert refs[0] != refs[1]
    assert "aaaaaaaa" in refs[0]
    assert "bbbbbbbb" in refs[1]


def test_legacy_filename_only_source_still_parses() -> None:
    fenced = wrap_untrusted_tool_output("plain note", source="attachment:note.txt")
    assert citation_refs_from_untrusted_context(fenced) == ("note.txt",)


def test_empty_untrusted_has_no_citations() -> None:
    assert citation_refs_from_untrusted_context("") == ()
    assert citation_refs_from_untrusted_context("   ") == ()


def test_sanitize_source_refs_drops_uuids_pages_and_duplicate_hash_chips() -> None:
    """LLM clean names + internal hash#pN citations collapse to one chip per file."""
    refs = sanitize_source_refs(
        (
            str(_ID_A),
            "1.pdf",
            "2.pdf",
            "3.pdf",
            "1.pdf#4a742ff9#p1",
            "2.pdf#85926613#p1",
            "3.pdf#8e04eee6#p1",
            "1.pdf#4a742ff9#p1",
            "  ",
        )
    )
    assert refs == ("1.pdf", "2.pdf", "3.pdf")


def test_sanitize_keeps_id_when_same_filename_collides() -> None:
    refs = sanitize_source_refs(
        (
            "report.pdf#aaaaaaaa#p1",
            "report.pdf#bbbbbbbb#p2",
        )
    )
    assert refs == ("report.pdf#aaaaaaaa", "report.pdf#bbbbbbbb")

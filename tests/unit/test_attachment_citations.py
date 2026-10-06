# tests/unit/test_attachment_citations.py

"""Attachment file/page citation labels from fenced turn context (W2 G03)."""

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


def test_citations_include_pages() -> None:
    body = "[[page 1]]\nHello\n[[page 2]]\nWorld"
    source = attachment_fence_source(attachment_id=_ID_A, filename="report.pdf")
    fenced = wrap_untrusted_tool_output(body, source=source)
    assert citation_refs_from_untrusted_context(fenced) == ("report.pdf#aaaaaaaa#p1", "report.pdf#aaaaaaaa#p2")


def test_citations_cap_many_pages_to_file_span() -> None:
    """Long PDFs must not dump every page chip (looks like retrieval noise)."""
    pages = "\n".join(f"[[page {n}]]\nchunk {n}" for n in range(1, 33))
    source = attachment_fence_source(attachment_id=_ID_A, filename="СФОТ_Банки.pdf")
    fenced = wrap_untrusted_tool_output(pages, source=source)
    refs = citation_refs_from_untrusted_context(fenced)
    assert refs == (
        "СФОТ_Банки.pdf#aaaaaaaa",
        "СФОТ_Банки.pdf#aaaaaaaa#p1",
        "СФОТ_Банки.pdf#aaaaaaaa#p32",
    )


def test_citations_filename_only_without_pages() -> None:
    source = attachment_fence_source(attachment_id=_ID_A, filename="note.txt")
    fenced = wrap_untrusted_tool_output("plain note", source=source)
    assert citation_refs_from_untrusted_context(fenced) == ("note.txt#aaaaaaaa",)


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


def test_sanitize_source_refs_drops_bare_uuids() -> None:
    refs = sanitize_source_refs(
        (
            str(_ID_A),
            "report.pdf#aaaaaaaa#p1",
            str(_ID_B),
            "report.pdf#aaaaaaaa#p1",
            "  ",
        )
    )
    assert refs == ("report.pdf#aaaaaaaa#p1",)

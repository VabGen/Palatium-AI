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


def test_sanitize_drops_attachment_uuid_fence_echo() -> None:
    """Live UI bug: LLM puts fence source ``attachment:<uuid>`` into source_refs."""
    refs = sanitize_source_refs(
        (
            f"attachment:{_ID_A}",
            f"attachment:{_ID_A}:Обращение.docx",
            "Обращение.docx",
            "attachment:note.txt",
        )
    )
    assert refs == ("Обращение.docx", "note.txt")


def test_sanitize_collapses_space_underscore_aliases() -> None:
    """LLM prose titles must not double the upload basename chips."""
    refs = sanitize_source_refs(
        (
            "Договор оказания услуг_2.docx",
            "Договор оказания услуг.docx",
            "Договор_оказания_услуг_2.docx",
            "Договор_оказания_услуг.docx",
        )
    )
    assert refs == ("Договор_оказания_услуг_2.docx", "Договор_оказания_услуг.docx")


def test_sanitize_collapses_markdown_bracket_aliases() -> None:
    """LLM ``[Скан 1.pdf]`` must not duplicate the upload basename chip."""
    refs = sanitize_source_refs(
        (
            "[Скан 1 _Приложение.pdf]",
            "[Скан 2 _Приложение.pdf]",
            "Скан_1__Приложение.pdf",
            "Скан_2__Приложение.pdf",
        )
    )
    assert refs == ("Скан_1__Приложение.pdf", "Скан_2__Приложение.pdf")


def test_align_formatter_meta_does_not_stamp_fence_as_source_refs() -> None:
    """Sticky rehydrate must not auto-chip PDFs on answers that never cited them."""
    from palatium_ai.application.agents.formatter.parsing import align_formatter_meta
    from palatium_ai.domain.agents.context_packet import ContextPacket
    from palatium_ai.domain.agents.formatter import FormatterInput
    from palatium_ai.domain.content.content_document import ContentDocument, DocumentMeta, ParagraphBlock
    from palatium_ai.domain.mcp.models import ToolExecutionPlan

    source = attachment_fence_source(attachment_id=_ID_A, filename="Скан_2__Приложение.pdf")
    fenced = wrap_untrusted_tool_output("scan body", source=source)
    document = ContentDocument(
        locale="ru-RU",
        blocks=(ParagraphBlock(text="Ваше имя — Геннадий."),),
        meta=DocumentMeta(confidence=0.9, requires_review=False, source_refs=()),
    )
    aligned = align_formatter_meta(
        document,
        FormatterInput(
            task_id="t1",
            context_packet=ContextPacket(
                task_id="t1",
                user_text="как меня зовут?",
                task_kind="knowledge_request",
                route="researcher",
                route_plan="answer",
                requires_mcp=False,
                candidate_capabilities=(),
                execution_plan=ToolExecutionPlan(
                    strategy="reason_only",
                    requires_tool_call=False,
                    rationale="memory",
                ),
                context_summary="name",
                untrusted_context=fenced,
            ),
            worker_summary="name from memory",
            response_locale="ru-RU",
        ),
    )
    assert aligned.meta.source_refs == ()

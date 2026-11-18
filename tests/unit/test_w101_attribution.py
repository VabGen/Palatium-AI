"""W10.1 P0.2 — medium recall must not claim «current session»."""

from __future__ import annotations

from palatium_ai.domain.content import ContentDocument, DocumentMeta, ParagraphBlock
from palatium_ai.domain.policies.attribution import MEMORY_SOURCE_MARKER, AttributionPolicy


def test_w101_attribution_marks_source() -> None:
    doc = ContentDocument(
        schema_version=1,
        locale="ru-RU",
        title=None,
        blocks=(
            ParagraphBlock(
                type="paragraph",
                text=("У меня нет информации о проекте Зенит. В контексте текущей сессии упоминается только проект BGT-42."),
            ),
        ),
        actions=(),
        meta=DocumentMeta(confidence=0.9, requires_review=False, source_refs=()),
    )
    out = AttributionPolicy.rewrite_false_current_session(doc, memory_hints=("бюджет 4.2 млн, код BGT-42",))
    text = " ".join(b.text for b in out.blocks if isinstance(b, ParagraphBlock))
    assert "текущей сессии" not in text.casefold()
    assert "сохранённой памяти" in text.casefold() or MEMORY_SOURCE_MARKER in out.meta.source_refs
    assert MEMORY_SOURCE_MARKER in out.meta.source_refs


def test_w101_attribution_current_session_no_marker() -> None:
    doc = ContentDocument(
        schema_version=1,
        locale="ru-RU",
        title=None,
        blocks=(ParagraphBlock(type="paragraph", text="Код проекта — ZNT-2026."),),
        actions=(),
        meta=DocumentMeta(confidence=1.0, requires_review=False, source_refs=()),
    )
    out = AttributionPolicy.rewrite_false_current_session(doc, memory_hints=())
    assert out.meta.source_refs == ()
    assert out.blocks == doc.blocks


def test_w101_attribution_rewrites_this_dialog_frame() -> None:
    """W10 §5: cross-thread medium must not read as «в этом диалоге»."""
    doc = ContentDocument(
        schema_version=1,
        locale="ru-RU",
        title=None,
        blocks=(
            ParagraphBlock(
                type="paragraph",
                text="В этом диалоге упоминается проект BGT-42 с бюджетом 4.2 млн.",
            ),
        ),
        actions=(),
        meta=DocumentMeta(confidence=0.8, requires_review=False, source_refs=()),
    )
    out = AttributionPolicy.rewrite_false_current_session(doc, memory_hints=("BGT-42 бюджет 4.2 млн",))
    text = " ".join(b.text for b in out.blocks if isinstance(b, ParagraphBlock))
    assert "этом диалоге" not in text.casefold()
    assert "сохранённой памяти" in text.casefold()
    assert MEMORY_SOURCE_MARKER in out.meta.source_refs


def test_attribution_preserves_file_inventory_refusal_with_pdf_dot() -> None:
    """Live UX: memory rewrite must not eat «В этом диалоге несколько файлов: ….pdf».

    The session-claim regex stopped at the extension dot and left
    «Из сохранённой памяти….pdf», «ht_1-5.webp» — a false memory filename (055).
    """
    from palatium_ai.domain.policies.file_reference import FileReferencePolicy, FileReferenceResolution

    refusal = FileReferencePolicy.refusal_message(
        FileReferenceResolution(
            status="ambiguous",
            reason="several_thread_files",
            candidates=("Заявка_сведения_СЭД.pdf", "ht_1-5.webp"),
        )
    )
    doc = ContentDocument(
        schema_version=1,
        locale="ru-RU",
        title=None,
        blocks=(ParagraphBlock(type="paragraph", text=refusal),),
        actions=(),
        meta=DocumentMeta(confidence=1.0, requires_review=False, source_refs=()),
    )
    out = AttributionPolicy.rewrite_false_current_session(
        doc,
        memory_hints=("факт из medium, не про файлы диалога",),
    )
    text = " ".join(b.text for b in out.blocks if isinstance(b, ParagraphBlock))
    assert text == refusal
    assert "сохранённой памяти" not in text.casefold()
    assert "Заявка_сведения_СЭД.pdf" in text
    assert "ht_1-5.webp" in text
    # Marker still records that medium hints were present this turn.
    assert MEMORY_SOURCE_MARKER in out.meta.source_refs

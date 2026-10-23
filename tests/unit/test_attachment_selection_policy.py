"""Attachment selection policy: Level 1 priority hierarchy + modality filter (055)."""

from __future__ import annotations

from collections.abc import Sequence
from uuid import uuid4

from palatium_ai.domain.attachments.context import AttachmentContextBlock
from palatium_ai.domain.memory.tool_output import wrap_untrusted_tool_output
from palatium_ai.domain.policies.attachment_selection import AttachmentSelectionPolicy


def _block(
    filename: str,
    *,
    mime_type: str = "application/pdf",
    text_state: str = "extracted",
    body: str = "Условия договора: срок 12 месяцев.",
) -> AttachmentContextBlock:
    return AttachmentContextBlock(
        attachment_id=uuid4(),
        filename=filename,
        source=f"attachment:{filename}",
        fenced_text=wrap_untrusted_tool_output(body, source=f"attachment:{filename}"),
        action="allow",
        mime_type=mime_type,
        text_state=text_state,  # type: ignore[arg-type]  # test builds both closed states
    )


def _names(blocks: Sequence[AttachmentContextBlock]) -> tuple[str, ...]:
    return tuple(block.filename for block in blocks)


def test_no_blocks_selects_nothing() -> None:
    selection = AttachmentSelectionPolicy.select(())

    assert selection.status == "none"
    assert selection.reason == "no_turn_attachments"


def test_one_file_is_always_unambiguous() -> None:
    block = _block("ht_1-5.webp", mime_type="image/webp")

    selection = AttachmentSelectionPolicy.select((block,), scope="single")

    assert selection.status == "selected"
    assert selection.blocks == (block,)
    assert selection.whole_set is True


def test_general_ask_takes_every_turn_file() -> None:
    """Priority 1 for a general ask: the current turn's whole set, never history."""
    blocks = (_block("a.pdf"), _block("b.pdf"), _block("c.pdf"))

    selection = AttachmentSelectionPolicy.select(blocks, scope="auto", ask="сделай план по документам")

    assert selection.status == "selected"
    assert _names(selection.blocks) == ("a.pdf", "b.pdf", "c.pdf")
    assert selection.whole_set is True


def test_explicit_filename_narrows_the_set() -> None:
    blocks = (_block("a.pdf"), _block("b.pdf"))

    selection = AttachmentSelectionPolicy.select(blocks, ask="перечитай b.pdf и дай текст")

    assert selection.status == "selected"
    assert _names(selection.blocks) == ("b.pdf",)
    assert selection.reason == "explicit_name"


def test_singular_ask_over_several_files_asks_the_human() -> None:
    blocks = (_block("a.pdf"), _block("b.pdf"))

    selection = AttachmentSelectionPolicy.select(blocks, scope="single", ask="дай текст файла")

    assert selection.status == "ambiguous"
    assert selection.candidates == ("a.pdf", "b.pdf")
    assert selection.blocks == ()


def test_singular_ask_with_several_named_files_is_ambiguous() -> None:
    blocks = (_block("a.pdf"), _block("b.pdf"))

    selection = AttachmentSelectionPolicy.select(
        blocks,
        scope="single",
        ask="сравни a.pdf и b.pdf",
    )

    assert selection.status == "ambiguous"
    assert selection.reason == "several_explicit_names_single_ask"


def test_explicit_plural_names_select_only_those_files() -> None:
    blocks = (_block("a.pdf"), _block("b.pdf"), _block("c.pdf"))

    selection = AttachmentSelectionPolicy.select(blocks, ask="сравни a.pdf и b.pdf")

    assert selection.status == "selected"
    assert _names(selection.blocks) == ("a.pdf", "b.pdf")
    assert selection.whole_set is False


def test_image_ask_filters_out_documents() -> None:
    """Level 1 type filter: "что на картинке" must not load the PDF."""
    pdf = _block("dogovor.pdf")
    image = _block("scan.webp", mime_type="image/webp")

    selection = AttachmentSelectionPolicy.select((pdf, image), kind="image", ask="что на картинке?")

    assert selection.status == "selected"
    assert _names(selection.blocks) == ("scan.webp",)
    assert selection.whole_set is False


def test_image_ask_without_images_keeps_real_files() -> None:
    """A named modality the turn lacks must not yield an empty prompt context."""
    blocks = (_block("a.pdf"), _block("b.pdf"))

    selection = AttachmentSelectionPolicy.select(blocks, kind="image", ask="что на картинке?")

    assert selection.status == "selected"
    assert _names(selection.blocks) == ("a.pdf", "b.pdf")
    assert selection.reason.startswith("kind_no_match_")
    assert selection.whole_set is True


def test_document_ask_ignores_image_uploads() -> None:
    image = _block("scan.webp", mime_type="image/webp")
    pdf = _block("contract.pdf")

    selection = AttachmentSelectionPolicy.select((image, pdf), kind="document")

    assert _names(selection.blocks) == ("contract.pdf",)


def test_needs_decision_only_for_multi_file_asks() -> None:
    one = (_block("a.pdf"),)
    several = (_block("a.pdf"), _block("b.pdf"))

    assert AttachmentSelectionPolicy.needs_decision(one, scope="single", kind="any") is False
    assert AttachmentSelectionPolicy.needs_decision(several, scope="auto", kind="any") is False
    assert AttachmentSelectionPolicy.needs_decision(several, scope="single", kind="any") is True
    assert AttachmentSelectionPolicy.needs_decision(several, scope="auto", kind="image") is True

"""Parser: <icon/> → typed icons; invalid names dropped; no emoji in text fields."""

from __future__ import annotations

from palatium_ai.application.agents.formatter.markdown_parser import markdown_to_content_document
from palatium_ai.domain.agents.context_packet import ContextPacket
from palatium_ai.domain.agents.formatter import FormatterInput
from palatium_ai.domain.content import CalloutBlock, HeadingBlock, ListBlock, ParagraphBlock
from palatium_ai.domain.mcp.models import ToolExecutionPlan


def _task() -> FormatterInput:
    return FormatterInput(
        task_id="t1",
        context_packet=ContextPacket(
            task_id="t1",
            user_text="hi",
            task_kind="knowledge_request",
            route="researcher",
            route_plan="answer",
            requires_mcp=False,
            execution_plan=ToolExecutionPlan(
                strategy="reason_only",
                requires_tool_call=False,
                rationale="r",
            ),
            context_summary="s",
        ),
        worker_summary="x",
        response_locale="en-US",
    )


def test_valid_icon_on_heading() -> None:
    md = '# <icon name="document"/> Report\n\nBody.\n'
    doc = markdown_to_content_document(md, _task())
    heading = next(b for b in doc.blocks if isinstance(b, HeadingBlock))
    assert heading.icon == "document"
    assert "<icon" not in heading.text
    assert "Report" in heading.text


def test_invalid_icon_name_dropped() -> None:
    md = '# <icon name="phone"/> Call\n\nBody.\n'
    doc = markdown_to_content_document(md, _task())
    heading = next(b for b in doc.blocks if isinstance(b, HeadingBlock))
    assert heading.icon is None
    assert "<icon" not in heading.text
    assert "Call" in heading.text


def test_callout_leading_icon_overrides_default() -> None:
    md = '> [!WARNING]\n> <icon name="warning"/> Watch out.\n'
    doc = markdown_to_content_document(md, _task())
    assert isinstance(doc.blocks[0], CalloutBlock)
    assert doc.blocks[0].icon == "warning"
    assert "<icon" not in doc.blocks[0].body
    assert "Watch out" in doc.blocks[0].body


def test_list_item_leading_icon() -> None:
    md = '- <icon name="check"/> Done item\n- plain\n'
    doc = markdown_to_content_document(md, _task())
    assert isinstance(doc.blocks[0], ListBlock)
    assert doc.blocks[0].items[0].icon == "check"
    assert "<icon" not in doc.blocks[0].items[0].text
    assert doc.blocks[0].items[1].icon is None


def test_emoji_absent_from_document_text() -> None:
    md = "## Section 📋\n\nDetails ⚠️ here.\n"
    doc = markdown_to_content_document(md, _task())
    prose = doc.plain_text()
    assert "📋" not in prose
    assert "⚠" not in prose
    assert "✅" not in prose


def test_paragraph_preserves_leading_icon() -> None:
    md = '<icon name="info"/> Hello paragraph.\n'
    doc = markdown_to_content_document(md, _task())
    paragraph = next(b for b in doc.blocks if isinstance(b, ParagraphBlock))
    assert paragraph.icon == "info"
    assert "<icon" not in paragraph.text
    assert "Hello paragraph" in paragraph.text


def test_x_attr_normalized_on_heading() -> None:
    md = '# <icon x="check"/> Done\n\nBody.\n'
    doc = markdown_to_content_document(md, _task())
    heading = next(b for b in doc.blocks if isinstance(b, HeadingBlock))
    assert heading.icon == "check"
    assert "<icon" not in heading.text


def test_mid_text_icon_stripped_not_left_as_raw() -> None:
    md = "See the <icon name=\"check\"/> mark.\n"
    doc = markdown_to_content_document(md, _task())
    paragraph = next(b for b in doc.blocks if isinstance(b, ParagraphBlock))
    assert paragraph.icon is None
    assert "<icon" not in paragraph.text
    assert "mark" in paragraph.text


def test_orphan_icon_paragraph_merges_into_following_heading() -> None:
    md = '<icon name="check"/>\n\n## Requirements\n\nBody.\n'
    doc = markdown_to_content_document(md, _task())
    heading = next(b for b in doc.blocks if isinstance(b, HeadingBlock))
    assert heading.icon == "check"
    assert "Requirements" in heading.text
    orphans = [
        b
        for b in doc.blocks
        if isinstance(b, ParagraphBlock) and b.icon is not None and not b.text.strip()
    ]
    assert orphans == []


def test_adjacent_ordered_lists_merge_for_continuous_numbering() -> None:
    from palatium_ai.application.agents.formatter.markdown_parser import _normalize_blocks
    from palatium_ai.domain.content.content_document import ListItem

    blocks = (
        ListBlock(type="list", style="ordered", items=(ListItem(text="First step"),)),
        ListBlock(type="list", style="ordered", items=(ListItem(text="Second step"),)),
        ParagraphBlock(type="paragraph", text="After lists."),
    )
    out = _normalize_blocks(blocks)
    ordered = [b for b in out if isinstance(b, ListBlock) and b.style == "ordered"]
    assert len(ordered) == 1
    assert len(ordered[0].items) == 2
    assert ordered[0].items[0].text == "First step"
    assert ordered[0].items[1].text == "Second step"

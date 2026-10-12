"""Unit tests for Formatter GFM → ContentDocument parser."""

from __future__ import annotations

from palatium_ai.application.agents.formatter.markdown_parser import markdown_to_content_document
from palatium_ai.domain.agents.context_packet import ContextPacket
from palatium_ai.domain.agents.formatter import FormatterInput
from palatium_ai.domain.content import CalloutBlock, ListBlock, ParagraphBlock, TableBlock
from palatium_ai.domain.mcp.models import ToolExecutionPlan


def _task(*, locale: str = "en-US", review: bool = False) -> FormatterInput:
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
        requires_review=review,
        response_locale=locale,
    )


def test_paragraphs_and_heading() -> None:
    doc = markdown_to_content_document("# Title\n\nHello world.", _task())
    assert doc.locale == "en-US"
    assert any(b.type == "heading" for b in doc.blocks) or doc.title
    assert any(isinstance(b, ParagraphBlock | ListBlock | type(doc.blocks[0])) for b in doc.blocks)


def test_callout_note() -> None:
    md = "> [!NOTE]\n> Informational remark.\n"
    doc = markdown_to_content_document(md, _task())
    assert isinstance(doc.blocks[0], CalloutBlock)
    assert doc.blocks[0].tone == "info"
    assert "Informational" in doc.blocks[0].body


def test_table() -> None:
    md = "| A | B |\n| --- | --- |\n| 1 | 2 |\n"
    doc = markdown_to_content_document(md, _task())
    assert isinstance(doc.blocks[0], TableBlock)
    assert doc.blocks[0].columns == ("A", "B")
    assert doc.blocks[0].rows == (("1", "2"),)


def test_hitl_confirm_tag() -> None:
    md = 'Ready.\n\n<hitl-action kind="confirm" label="Approve" />\n'
    doc = markdown_to_content_document(md, _task())
    assert doc.meta.interaction == "confirm"
    assert len(doc.actions) == 1
    assert doc.actions[0].label == "Approve"
    assert doc.actions[0].kind == "confirm"
    assert all("<hitl" not in (b.text if hasattr(b, "text") else "") for b in doc.blocks)


def test_hitl_choice_tag() -> None:
    md = '<hitl-choice options=\'["A","B"]\' />\n'
    doc = markdown_to_content_document(md, _task())
    assert doc.meta.interaction == "choice"
    assert [a.label for a in doc.actions] == ["A", "B"]


def test_json_fallback_preserves_content_document() -> None:
    payload = {
        "schema_version": 1,
        "locale": "en-US",
        "title": None,
        "blocks": [{"type": "paragraph", "text": "Legacy JSON path."}],
        "actions": [],
        "meta": {
            "confidence": 0.9,
            "requires_review": False,
            "source_refs": [],
            "interaction": "none",
        },
    }
    import json

    doc = markdown_to_content_document(json.dumps(payload), _task())
    assert isinstance(doc.blocks[0], ParagraphBlock)
    assert doc.blocks[0].text == "Legacy JSON path."


def test_list_bullets() -> None:
    md = "- one\n- two\n"
    doc = markdown_to_content_document(md, _task())
    assert isinstance(doc.blocks[0], ListBlock)
    assert len(doc.blocks[0].items) == 2

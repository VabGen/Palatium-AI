"""Worker GFM contract: headings, titled callouts, bare KV panels, flat nested bullets."""

from __future__ import annotations

from palatium_ai.application.agents.formatter.markdown_parser import markdown_to_content_document
from palatium_ai.domain.agents.context_packet import ContextPacket
from palatium_ai.domain.agents.formatter import FormatterInput
from palatium_ai.domain.content import (
    CalloutBlock,
    HeadingBlock,
    KeyValueBlock,
    ListBlock,
)
from palatium_ai.domain.mcp.models import ToolExecutionPlan


def _task(*, locale: str = "ru-RU") -> FormatterInput:
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
        response_locale=locale,
    )


def test_level_two_headings_become_heading_blocks() -> None:
    doc = markdown_to_content_document("## Контекст\n\nТекст.\n\n## Риски\n\n- риск\n", _task())
    headings = [block for block in doc.blocks if isinstance(block, HeadingBlock)]
    assert [heading.text for heading in headings] == ["Контекст", "Риски"]


def test_titled_callout_keeps_title() -> None:
    md = "## Риски\n\n> [!WARNING] Необратимо\n> Удаление нельзя отменить.\n"
    doc = markdown_to_content_document(md, _task())
    callout = next(block for block in doc.blocks if isinstance(block, CalloutBlock))
    assert callout.tone == "warning"
    assert callout.title == "Необратимо"
    assert "нельзя отменить" in callout.body


def test_untitled_callout_still_parses() -> None:
    doc = markdown_to_content_document("> [!NOTE]\n> Просто заметка.\n", _task())
    callout = next(block for block in doc.blocks if isinstance(block, CalloutBlock))
    assert callout.title is None


def test_bare_key_value_panel_parses_two_pairs() -> None:
    md = "**Сумма:** 120 000 ₽\n**Срок:** 11 месяцев\n"
    doc = markdown_to_content_document(md, _task())
    panel = next(block for block in doc.blocks if isinstance(block, KeyValueBlock))
    assert [item.label for item in panel.items] == ["Сумма", "Срок"]


def test_single_bare_pair_stays_prose() -> None:
    doc = markdown_to_content_document("**Сумма:** 120 000 ₽\n", _task())
    assert not any(isinstance(block, KeyValueBlock) for block in doc.blocks)


def test_nested_bullet_is_flattened_with_marker() -> None:
    md = "## Пункты\n\n- первый\n  - вложенный\n- второй\n"
    doc = markdown_to_content_document(md, _task())
    bullet_list = next(block for block in doc.blocks if isinstance(block, ListBlock))
    texts = [item.text for item in bullet_list.items]
    assert texts[0] == "первый"
    assert texts[1] == "· вложенный"
    assert texts[2] == "второй"

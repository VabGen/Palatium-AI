"""GFM rich-block parsing: divider, formula, key-value panel, steps (Phase 0.2)."""

from __future__ import annotations

from palatium_ai.application.agents.formatter.markdown_parser import (
    _try_parse_kv_panel,
    _try_parse_steps,
    markdown_to_content_document,
)
from palatium_ai.domain.agents.context_packet import ContextPacket
from palatium_ai.domain.agents.formatter import FormatterInput
from palatium_ai.domain.content import (
    DividerBlock,
    FormulaBlock,
    KeyValueBlock,
    StepsBlock,
)
from palatium_ai.domain.mcp.models import ToolExecutionPlan


def _task(*, locale: str = "en-US") -> FormatterInput:
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


# --- helper-level -------------------------------------------------------


def test_parse_kv_panel() -> None:
    lines = ["- **Параметр:** значение", "- **Статус:** активно"]
    block, consumed = _try_parse_kv_panel(lines, 0)
    assert isinstance(block, KeyValueBlock)
    assert len(block.items) == 2
    assert block.items[0].label == "Параметр"
    assert block.items[0].value == "значение"
    assert consumed == 2


def test_parse_steps() -> None:
    lines = ["1. **Шаг 1:** описание", "2. **Шаг 2:** описание"]
    block, consumed = _try_parse_steps(lines, 0)
    assert isinstance(block, StepsBlock)
    assert len(block.items) == 2
    assert block.items[0].title == "Шаг 1"
    assert consumed == 2


def test_single_kv_item_is_not_a_panel() -> None:
    block, consumed = _try_parse_kv_panel(["- **Только один:** без пары"], 0)
    assert block is None
    assert consumed == 0


def test_single_step_is_not_a_timeline() -> None:
    block, consumed = _try_parse_steps(["1. **Шаг:** один"], 0)
    assert block is None
    assert consumed == 0


# --- end-to-end through markdown_to_content_document --------------------


def test_divider_block() -> None:
    doc = markdown_to_content_document("Above\n\n---\n\nBelow", _task())
    assert any(isinstance(b, DividerBlock) for b in doc.blocks)


def test_formula_block() -> None:
    doc = markdown_to_content_document("$$E = mc^2$$", _task())
    assert isinstance(doc.blocks[0], FormulaBlock)
    assert doc.blocks[0].latex == "E = mc^2"


def test_kv_panel_block() -> None:
    md = "- **Параметр:** значение\n- **Статус:** активно\n"
    doc = markdown_to_content_document(md, _task())
    assert isinstance(doc.blocks[0], KeyValueBlock)
    assert [item.label for item in doc.blocks[0].items] == ["Параметр", "Статус"]


def test_steps_block() -> None:
    md = "1. **Первый шаг:** описание\n2. **Второй шаг:** описание\n"
    doc = markdown_to_content_document(md, _task())
    assert isinstance(doc.blocks[0], StepsBlock)
    assert doc.blocks[0].items[0].title == "Первый шаг"


def test_single_bullet_with_bold_label_is_not_a_panel() -> None:
    doc = markdown_to_content_document("- **Только один:** значение\n", _task())
    assert not any(isinstance(b, KeyValueBlock) for b in doc.blocks)
    assert "значение" in doc.plain_text()


def test_table_still_parses_with_separator() -> None:
    md = "| A | B |\n| --- | --- |\n| 1 | 2 |\n"
    doc = markdown_to_content_document(md, _task())
    assert doc.blocks[0].type == "table"
    assert doc.blocks[0].columns == ("A", "B")

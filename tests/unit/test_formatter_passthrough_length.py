"""Passthrough covers short plain prose and still refuses structured answers."""

from __future__ import annotations

import pytest

from palatium_ai.application.agents.formatter.config import FORMATTER_PASSTHROUGH_MAX_CHARS
from palatium_ai.application.agents.formatter.fast_path import try_formatter_fast_path
from palatium_ai.domain.agents.context_packet import ContextPacket
from palatium_ai.domain.agents.formatter import FormatterInput
from palatium_ai.domain.content.markdown_blocks import plain_paragraph_count
from palatium_ai.domain.mcp.models import ToolExecutionPlan


def _input(worker: str) -> FormatterInput:
    packet = ContextPacket(
        task_id="t1",
        user_text="скажи коротко",
        task_kind="knowledge_request",
        route="researcher",
        route_plan="answer",
        requires_mcp=False,
        execution_plan=ToolExecutionPlan(strategy="reason_only", requires_tool_call=False, rationale="r"),
        context_summary="s",
    )
    return FormatterInput(
        task_id="t1",
        context_packet=packet,
        worker_summary=worker,
        response_locale="ru-RU",
    )


def _plain(length: int) -> str:
    return ("Ответ без разметки. " * (length // 4 + 1))[:length]


@pytest.mark.parametrize("length", (100, 300, 500))
def test_plain_prose_within_limit_skips_formatter_llm(length: int) -> None:
    prose = _plain(length)
    assert plain_paragraph_count(prose) is not None
    result = try_formatter_fast_path(
        task_input=_input(prose),
        task_kind="knowledge_request",
        selected_strategy="reason_only",
        worker_confidence=0.9,
    )
    assert result is not None
    assert result.output is not None
    assert [block.type for block in result.output.blocks] == ["paragraph"]


def test_plain_prose_over_limit_keeps_formatter_llm() -> None:
    prose = _plain(FORMATTER_PASSTHROUGH_MAX_CHARS + 1)
    result = try_formatter_fast_path(
        task_input=_input(prose),
        task_kind="knowledge_request",
        selected_strategy="reason_only",
        worker_confidence=0.9,
    )
    assert result is None


def test_untrusted_envelope_is_not_plain_prose() -> None:
    prose = (
        "<<<UNTRUSTED_TOOL_OUTPUT source=mcp:platform.search_knowledge>>> "
        "Краткий ответ без разметки. "
        "<<<END_UNTRUSTED_TOOL_OUTPUT>>>"
    )
    assert plain_paragraph_count(prose) is not None
    result = try_formatter_fast_path(
        task_input=_input(prose),
        task_kind="knowledge_request",
        selected_strategy="reason_only",
        worker_confidence=0.9,
    )
    assert result is None


def test_structured_answer_inside_char_limit_keeps_formatter_llm() -> None:
    lines = ["План:"] + [f"- пункт {index}: проверить документ и срок" for index in range(1, 9)]
    structured = "\n".join(lines)
    assert 200 <= len(structured) <= FORMATTER_PASSTHROUGH_MAX_CHARS
    assert plain_paragraph_count(structured) is None
    result = try_formatter_fast_path(
        task_input=_input(structured),
        task_kind="knowledge_request",
        selected_strategy="reason_only",
        worker_confidence=0.9,
    )
    assert result is None

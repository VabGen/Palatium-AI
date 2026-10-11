"""Formatter fast-path emit — ContentDocument without LLM."""

from __future__ import annotations

from palatium_ai.application.agents.formatter.fast_path import (
    document_from_source_content,
    try_formatter_fast_path,
)
from palatium_ai.domain.agents.context_packet import ContextPacket
from palatium_ai.domain.agents.formatter import FormatterInput
from palatium_ai.domain.mcp.models import ToolExecutionPlan


def _task(
    *,
    worker: str = "Ready prior answer.",
    task_kind: str = "response_formatting",
    strategy: str = "format_only",
) -> FormatterInput:
    packet = ContextPacket(
        task_id="t1",
        user_text="reformat that",
        task_kind=task_kind,  # type: ignore[arg-type]
        route="formatter",
        route_plan="Format prior answer",
        requires_mcp=False,
        candidate_capabilities=("format",),
        execution_plan=ToolExecutionPlan(
            strategy=strategy,  # type: ignore[arg-type]
            requires_tool_call=False,
            rationale="format continuation",
        ),
        context_summary="format_only",
    )
    return FormatterInput(
        task_id="t1",
        context_packet=packet,
        worker_summary=worker,
        response_locale="ru-RU",
    )


def test_document_from_source_chunks_long_text() -> None:
    long = ("абзац " * 2_000).strip()
    doc = document_from_source_content(long, task_input=_task())
    assert doc.locale == "ru-RU"
    assert len(doc.blocks) >= 2
    assert all(block.type == "paragraph" for block in doc.blocks)


def test_document_from_source_builds_ordered_list_with_emphasis() -> None:
    source = (
        "Анализ обращения МБОО «Доброе дело»:\n"
        "1. **Суть проблемы**: Родители жалуются на системные нарушения.\n"
        "2. Ключевые нарушения: отказ в допуске тьюторов.\n"
        "- **Субъективность заключений** — без объективных критериев\n"
        "- отсутствие межведомственного взаимодействия\n"
    )
    doc = document_from_source_content(source, task_input=_task())
    assert doc.title == "Анализ обращения МБОО «Доброе дело»"
    assert any(block.type == "list" and block.style == "ordered" for block in doc.blocks)
    ordered = next(b for b in doc.blocks if b.type == "list" and b.style == "ordered")
    assert ordered.items[0].emphasis == "Суть проблемы"
    assert "Родители" in ordered.items[0].text
    assert ordered.items[1].emphasis == "Ключевые нарушения"
    unordered = next(b for b in doc.blocks if b.type == "list" and b.style == "unordered")
    assert unordered.items[0].emphasis == "Субъективность заключений"


def test_try_fast_path_always_defers_to_llm() -> None:
    """Presentation always needs Formatter LLM — node fast-path never emits."""
    for task_kind, strategy in (
        ("response_formatting", "format_only"),
        ("knowledge_request", "retrieve_then_reason"),
        ("knowledge_request", "reason_only"),
    ):
        result = try_formatter_fast_path(
            task_input=_task(
                worker="1. **Тема**: детали.\n2. Вывод: структура.",
                task_kind=task_kind,
                strategy=strategy,
            ),
            task_kind=task_kind,
            selected_strategy=strategy,
        )
        assert result is None


def test_try_fast_path_none_without_source() -> None:
    result = try_formatter_fast_path(
        task_input=_task(worker=""),
        task_kind="response_formatting",
        selected_strategy="format_only",
    )
    assert result is None

"""0-LLM mechanical restructure is tried before plain Formatter passthrough."""

from __future__ import annotations

from uuid import uuid4

from palatium_ai.application.agents.formatter.fast_path import try_formatter_fast_path
from palatium_ai.application.services.intent_turn_helpers import ASSISTANT_TURN_SCHEMA
from palatium_ai.application.services.turn_sse_bridge import TurnSseBridge, turn_sse_bridge
from palatium_ai.core.observability.metrics import agent_metrics
from palatium_ai.domain.agents.context_packet import ContextPacket
from palatium_ai.domain.agents.formatter import FormatterInput
from palatium_ai.domain.content.content_document import (
    ContentDocument,
    DocumentMeta,
    ListBlock,
    ListItem,
    ParagraphBlock,
    StepItem,
    StepsBlock,
)
from palatium_ai.domain.mcp.models import ToolExecutionPlan
from palatium_ai.domain.memory.turns import DialogTurn, DialogTurnWindow


def _packet(*, shape: str = "plan") -> ContextPacket:
    return ContextPacket(
        task_id="t-mech",
        user_text="оформи по шагам",
        task_kind="response_formatting",
        route="formatter",
        route_plan="format",
        requires_mcp=False,
        execution_plan=ToolExecutionPlan(
            strategy="format_only",
            requires_tool_call=False,
            rationale="r",
        ),
        context_summary="s",
        response_shape=shape,  # type: ignore[arg-type]
    )


def _window_with_document(document: ContentDocument) -> DialogTurnWindow:
    return DialogTurnWindow(
        thread_id="th",
        turns=(
            DialogTurn(
                id=uuid4(),
                thread_id="th",
                role="assistant",
                content=document.plain_text() or "prior",
                seq=1,
                payload={
                    "schema": ASSISTANT_TURN_SCHEMA,
                    "document": document.model_dump(mode="json"),
                },
            ),
        ),
    )


def test_mechanical_promotes_ordered_list_without_llm() -> None:
    prior = ContentDocument(
        locale="ru-RU",
        blocks=(
            ListBlock(
                style="ordered",
                items=(
                    ListItem(text="собрать", emphasis="Подготовка"),
                    ListItem(text="отправить", emphasis="Подача"),
                ),
            ),
        ),
        meta=DocumentMeta(confidence=0.9, kind="guide"),
    )
    task = FormatterInput(
        task_id="t-mech",
        context_packet=_packet(shape="plan"),
        worker_summary="",
        response_locale="ru-RU",
        transformation="restructure",
        dialog_window=_window_with_document(prior),
    )
    before = agent_metrics.response_shape_count("plan", "mechanical_promote")
    result = try_formatter_fast_path(
        task_input=task,
        task_kind="response_formatting",
        selected_strategy="format_only",
        worker_confidence=0.9,
    )
    assert result is not None
    assert result.output is not None
    assert isinstance(result.output.blocks[0], StepsBlock)
    assert result.output.blocks[0].items[0].title == "Подготовка"
    assert agent_metrics.response_shape_count("plan", "mechanical_promote") == before + 1


def test_mechanical_reuses_satisfying_steps() -> None:
    prior = ContentDocument(
        locale="ru-RU",
        blocks=(
            StepsBlock(
                items=(
                    StepItem(title="A", body="1"),
                    StepItem(title="B", body="2"),
                )
            ),
        ),
        meta=DocumentMeta(confidence=0.95, kind="guide"),
    )
    task = FormatterInput(
        task_id="t-mech-2",
        context_packet=_packet(shape="plan"),
        worker_summary="",
        response_locale="ru-RU",
        transformation="restructure",
        dialog_window=_window_with_document(prior),
    )
    before = agent_metrics.response_shape_count("plan", "mechanical_reuse")
    result = try_formatter_fast_path(
        task_input=task,
        task_kind="response_formatting",
        selected_strategy="format_only",
        worker_confidence=0.9,
    )
    assert result is not None
    assert result.output is not None
    assert result.output.blocks[0].type == "steps"
    assert agent_metrics.response_shape_count("plan", "mechanical_reuse") == before + 1


def test_mechanical_structured_preview_emits_block_delta_not_markdown() -> None:
    """schema_first canary: mechanical promote must paint StepsBlock, not answer_delta."""
    prior = ContentDocument(
        locale="ru-RU",
        blocks=(
            ListBlock(
                style="ordered",
                items=(
                    ListItem(text="собрать", emphasis="Подготовка"),
                    ListItem(text="отправить", emphasis="Подача"),
                ),
            ),
        ),
        meta=DocumentMeta(confidence=0.9, kind="guide"),
    )
    task = FormatterInput(
        task_id="t-mech-sse",
        context_packet=_packet(shape="plan"),
        worker_summary="",
        response_locale="ru-RU",
        transformation="restructure",
        dialog_window=_window_with_document(prior),
    )
    bridge = TurnSseBridge(stream_contract="structured_incremental")
    with turn_sse_bridge(bridge):
        result = try_formatter_fast_path(
            task_input=task,
            task_kind="response_formatting",
            selected_strategy="format_only",
            worker_confidence=0.9,
        )
    assert result is not None
    events: list[dict[str, object]] = []
    while not bridge.queue.empty():
        events.append(bridge.queue.get_nowait())
    assert [event["event"] for event in events] == ["block_delta"]
    assert events[0]["block"]["type"] == "steps"
    assert all("replace" not in event for event in events)


def test_mechanical_flattens_to_prose_without_llm() -> None:
    prior = ContentDocument(
        locale="ru-RU",
        blocks=(
            StepsBlock(
                items=(
                    StepItem(title="A", body="one"),
                    StepItem(title="B", body="two"),
                )
            ),
        ),
        meta=DocumentMeta(confidence=0.9, kind="guide"),
    )
    task = FormatterInput(
        task_id="t-mech-3",
        context_packet=_packet(shape="prose"),
        worker_summary="",
        response_locale="ru-RU",
        transformation="restructure",
        dialog_window=_window_with_document(prior),
    )
    before = agent_metrics.response_shape_count("prose", "mechanical_flatten")
    result = try_formatter_fast_path(
        task_input=task,
        task_kind="response_formatting",
        selected_strategy="format_only",
        worker_confidence=0.9,
    )
    assert result is not None
    assert result.output is not None
    assert all(isinstance(b, ParagraphBlock) for b in result.output.blocks)
    assert agent_metrics.response_shape_count("prose", "mechanical_flatten") == before + 1

"""Analysis inventories must not keep Steps number-badge chrome (055)."""

from __future__ import annotations

from palatium_ai.application.agents.formatter.parsing import align_formatter_meta
from palatium_ai.domain.agents.context_packet import ContextPacket
from palatium_ai.domain.agents.formatter import FormatterInput
from palatium_ai.domain.content.content_document import (
    ContentDocument,
    DocumentMeta,
    HeadingBlock,
    ListBlock,
    StepItem,
    StepsBlock,
)
from palatium_ai.domain.mcp.models import ToolExecutionPlan


def _formatter_input(*, response_shape: str = "document_analysis") -> FormatterInput:
    return FormatterInput(
        task_id="t1",
        context_packet=ContextPacket(
            task_id="t1",
            user_text="разбери приложение",
            task_kind="knowledge_request",
            route="researcher",
            route_plan="analyze",
            requires_mcp=False,
            candidate_capabilities=(),
            execution_plan=ToolExecutionPlan(
                strategy="reason_only",
                requires_tool_call=False,
                rationale="analysis",
            ),
            context_summary="doc",
            response_shape=response_shape,  # type: ignore[arg-type]
        ),
        worker_summary="x",
        response_locale="ru-RU",
    )


def test_align_demotes_statusless_steps_under_document_analysis() -> None:
    """Catalogue title/body pairs leave step badges for unordered bullets (dots)."""
    document = ContentDocument(
        locale="ru-RU",
        blocks=(
            HeadingBlock(level=2, text="Состав фоновой ИС", icon="folder"),
            StepsBlock(
                items=(
                    StepItem(title="Платформа", body="Сервисы."),
                    StepItem(title="UI", body="Формы."),
                )
            ),
        ),
        meta=DocumentMeta(confidence=0.9, kind="analysis"),
    )
    aligned = align_formatter_meta(document, _formatter_input(response_shape="document_analysis"))
    assert isinstance(aligned.blocks[1], ListBlock)
    assert aligned.blocks[1].style == "unordered"
    assert aligned.blocks[1].items[0].emphasis == "Платформа"
    assert aligned.blocks[1].items[0].icon is None


def test_align_demotes_advice_steps_to_checklist_not_kv() -> None:
    document = ContentDocument(
        locale="ru-RU",
        blocks=(
            HeadingBlock(level=2, text="Рекомендации", icon="check"),
            StepsBlock(
                items=(
                    StepItem(title="Права", body="Разграничить ИС."),
                    StepItem(title="OSS", body="Проверить лицензии."),
                )
            ),
        ),
        meta=DocumentMeta(confidence=0.9, kind="analysis"),
    )
    aligned = align_formatter_meta(document, _formatter_input(response_shape="document_analysis"))
    assert isinstance(aligned.blocks[1], ListBlock)
    assert aligned.blocks[1].style == "unordered"
    assert aligned.blocks[1].items[0].icon == "check"


def test_align_keeps_steps_for_plan_shape() -> None:
    document = ContentDocument(
        locale="ru-RU",
        blocks=(
            StepsBlock(
                items=(
                    StepItem(title="Собрать", body="Документы."),
                    StepItem(title="Подать", body="Заявление."),
                )
            ),
        ),
        meta=DocumentMeta(confidence=0.9, kind="guide"),
    )
    aligned = align_formatter_meta(document, _formatter_input(response_shape="plan"))
    assert isinstance(aligned.blocks[0], StepsBlock)

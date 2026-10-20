"""Deterministic render for worker-owned turns (P1b)."""

from __future__ import annotations

from palatium_ai.application.agents.formatter.worker_writer import render_worker_document
from palatium_ai.domain.agents.context_packet import ContextPacket
from palatium_ai.domain.agents.formatter import FormatterInput
from palatium_ai.domain.content import ContentDocument, HeadingBlock
from palatium_ai.domain.mcp.models import ToolExecutionPlan

_LONG_BODY = (
    "## Контекст\n\n"
    "Договор аренды заключён на одиннадцать месяцев, стороны согласовали порядок "
    "индексации и ответственность за просрочку платежа. Оплата производится двумя "
    "частями, каждая часть подтверждается актом, подписанным обеими сторонами. "
    "Изменение условий допускается только письменным соглашением.\n\n"
    "## Риски\n\n"
    "- штраф за досрочное расторжение предусмотрен только для арендатора;\n"
    "- индексация не ограничена верхним пределом;\n"
    "- порядок возврата обеспечительного платежа не описан.\n"
)


def _task(
    *,
    summary: str = _LONG_BODY,
    locale: str = "ru-RU",
    task_kind: str = "knowledge_request",
    capabilities: tuple[str, ...] = (),
) -> FormatterInput:
    return FormatterInput(
        task_id="t1",
        context_packet=ContextPacket(
            task_id="t1",
            user_text="hi",
            task_kind=task_kind,
            route="researcher",
            route_plan="answer",
            requires_mcp=False,
            execution_plan=ToolExecutionPlan(
                strategy="reason_only",
                requires_tool_call=False,
                rationale="r",
            ),
            context_summary="s",
            candidate_capabilities=capabilities,
        ),
        worker_summary=summary,
        response_locale=locale,
    )


def test_long_structured_draft_renders_without_llm() -> None:
    decision = render_worker_document(_task(), worker_confidence=0.9)
    assert decision.rendered
    document = decision.document
    assert isinstance(document, ContentDocument)
    assert any(isinstance(block, HeadingBlock) for block in document.blocks)
    assert document.locale == "ru-RU"
    assert document.meta.confidence == 0.9


def test_empty_draft_falls_back() -> None:
    decision = render_worker_document(_task(summary="   "), worker_confidence=0.9)
    assert decision.reason == "empty_source"
    assert decision.document is None


def test_low_confidence_falls_back() -> None:
    decision = render_worker_document(_task(), worker_confidence=0.4)
    assert decision.reason == "low_confidence"


def test_missing_confidence_falls_back() -> None:
    decision = render_worker_document(_task(), worker_confidence=None)
    assert decision.reason == "low_confidence"


def test_composition_request_falls_back_to_llm() -> None:
    decision = render_worker_document(_task(task_kind="response_formatting"), worker_confidence=0.9)
    assert decision.reason == "composition_required"


def test_truncated_draft_falls_back() -> None:
    decision = render_worker_document(_task(summary=_LONG_BODY.rstrip() + "…"), worker_confidence=0.9)
    assert decision.reason == "truncated"


def test_locale_mismatch_falls_back() -> None:
    decision = render_worker_document(_task(locale="en-US"), worker_confidence=0.9)
    assert decision.reason == "locale_mismatch"


def test_document_without_blocks_falls_back() -> None:
    hitl_only = '<hitl-action kind="confirm" label="OK"/>\n' * 20
    decision = render_worker_document(_task(summary=hitl_only), worker_confidence=0.9)
    assert decision.reason == "no_blocks"

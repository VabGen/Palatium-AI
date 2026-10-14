"""Generation asks keep their own shape: planner, Formatter style hint, passthrough.

Regression for the joke-after-document class: a creative ask went through
search_knowledge and the Formatter compiled it into icon sections (style_hint
``brand_sections_icons`` / ``restructure_sections_icons``).
"""

from __future__ import annotations

import pytest

from palatium_ai.application.agents.formatter.config import FORMATTER_PASSTHROUGH_MAX_CHARS
from palatium_ai.application.agents.formatter.fast_path import try_formatter_fast_path
from palatium_ai.application.agents.formatter.parsing import resolve_style_hint
from palatium_ai.application.services.execution_planner import ExecutionPlanner
from palatium_ai.domain.agents.context_packet import ContextPacket
from palatium_ai.domain.agents.context_weaver import ContextWeaverInput
from palatium_ai.domain.agents.formatter import FormatterInput
from palatium_ai.domain.mcp.models import ToolExecutionPlan
from palatium_ai.domain.policies import FormatterFastPathPolicy, FormatterPassthroughSignals

_JOKE = "Охранник спрашивает: «Вы на мероприятие?» — «Нет, я на договор». — «Тогда проходите по пункту 3.2»."
_STRUCTURED = "Итоги:\n1. **Риск**: сроки.\n2. **Действие**: продлить договор."


def _weaver_input(**overrides: object) -> ContextWeaverInput:
    base: dict[str, object] = {
        "task_id": "t1",
        "user_text": "расскажи анекдот на тему",
        "task_kind": "knowledge_request",
        "route": "researcher",
        "route_plan": "answer",
        "requires_mcp": False,
    }
    base.update(overrides)
    return ContextWeaverInput(**base)  # type: ignore[arg-type]  # test factory


@pytest.mark.asyncio()
async def test_compose_ask_reasons_without_search_knowledge() -> None:
    bundle = await ExecutionPlanner().build(_weaver_input(candidate_capabilities=("compose",)))
    assert bundle.selected_strategy == "reason_only"
    assert bundle.requires_tool_call is False


@pytest.mark.asyncio()
async def test_draft_ask_keeps_retrieval() -> None:
    bundle = await ExecutionPlanner().build(_weaver_input(candidate_capabilities=("draft",)))
    assert bundle.selected_strategy == "retrieve_then_reason"


@pytest.mark.asyncio()
async def test_compose_with_upload_stays_attachment_grounded() -> None:
    bundle = await ExecutionPlanner().build(
        _weaver_input(candidate_capabilities=("compose",), has_attachment_context=True),
    )
    assert bundle.selected_strategy == "reason_only"
    assert "attachment" in bundle.steps[0].rationale.lower()


def _formatter_input(
    *,
    worker: str,
    caps: tuple[str, ...] = (),
    task_kind: str = "knowledge_request",
    **overrides: object,
) -> FormatterInput:
    packet = ContextPacket(
        task_id="t1",
        user_text="расскажи анекдот на тему",
        task_kind=task_kind,  # type: ignore[arg-type]  # closed Literal; valid values
        route="researcher",
        route_plan="answer",
        requires_mcp=False,
        candidate_capabilities=caps,
        execution_plan=ToolExecutionPlan(strategy="reason_only", requires_tool_call=False, rationale="r"),
        context_summary="s",
    )
    fields: dict[str, object] = {
        "task_id": "t1",
        "context_packet": packet,
        "worker_summary": worker,
        "response_locale": "ru-RU",
    }
    fields.update(overrides)
    return FormatterInput(**fields)  # type: ignore[arg-type]  # test factory


@pytest.mark.parametrize(
    "caps,worker,expected",
    (
        (("compose",), _STRUCTURED, "content_generation"),
        (("draft",), _JOKE, "document_generation"),
        ((), _JOKE, "plain_text"),
        ((), _STRUCTURED, "brand_sections_icons"),
    ),
)
def test_style_hint_preserves_generated_shape(caps: tuple[str, ...], worker: str, expected: str) -> None:
    assert resolve_style_hint(_formatter_input(worker=worker, caps=caps)) == expected


def test_style_hint_long_structured_stays_plain() -> None:
    """Long legal/file answers must not burn hop budget on brand icon sections."""
    long_body = "Раздел А.\n\n" + ("Проверка соответствия статье закона. " * 20)
    assert len(long_body) >= 400
    assert resolve_style_hint(_formatter_input(worker=long_body, caps=())) == "plain_text"


def test_explicit_user_decisions_outrank_generation_hint() -> None:
    choice = _formatter_input(worker=_JOKE, caps=("compose",), requires_user_choice=True)
    reformat = _formatter_input(worker=_JOKE, caps=("compose",), task_kind="response_formatting")
    assert resolve_style_hint(choice) == "choice_cards"
    assert resolve_style_hint(reformat) == "restructure_sections_icons"


def _signals(**overrides: object) -> FormatterPassthroughSignals:
    base: dict[str, object] = {
        "source_chars": 40,
        "worker_confident": True,
        "source_is_plain_prose": True,
        "locale_matches": True,
    }
    base.update(overrides)
    return FormatterPassthroughSignals(**base)  # type: ignore[arg-type]  # test factory


def test_passthrough_short_plain_answer_skips_llm() -> None:
    decision = FormatterFastPathPolicy.decide(
        source_content="Да, договор действует до 31.12.",
        passthrough=_signals(),
        passthrough_max_chars=FORMATTER_PASSTHROUGH_MAX_CHARS,
    )
    assert decision.skip_llm is True
    assert decision.reason == "passthrough_plain_prose"


@pytest.mark.parametrize(
    "overrides,reason",
    (
        ({"worker_confident": False}, "worker_not_confident"),
        ({"source_chars": FORMATTER_PASSTHROUGH_MAX_CHARS + 1}, "source_exceeds_passthrough"),
        ({"source_is_plain_prose": False}, "source_has_structure"),
        ({"locale_matches": False}, "locale_mismatch"),
        ({"requires_review": True}, "requires_review"),
        ({"revision_requested": True}, "revision_requested"),
        ({"restructure_requested": True}, "restructure_requested"),
        ({"underspecification_kind": "open_text"}, "underspecified"),
    ),
)
def test_passthrough_blocked_by_any_signal(overrides: dict[str, object], reason: str) -> None:
    decision = FormatterFastPathPolicy.decide(
        source_content="Короткий ответ.",
        passthrough=_signals(**overrides),
        passthrough_max_chars=FORMATTER_PASSTHROUGH_MAX_CHARS,
    )
    assert decision.skip_llm is False
    assert decision.reason == reason


def test_fast_path_passthrough_emits_paragraph_verbatim() -> None:
    short = "Да, договор действует до 31.12."
    result = try_formatter_fast_path(
        task_input=_formatter_input(worker=short),
        task_kind="knowledge_request",
        selected_strategy="reason_only",
        worker_confidence=0.9,
    )
    assert result is not None
    assert result.output is not None
    assert result.output.title is None
    assert [block.type for block in result.output.blocks] == ["paragraph"]
    assert result.output.plain_text().strip() == short


def test_fast_path_never_passes_through_failed_worker_placeholder() -> None:
    result = try_formatter_fast_path(
        task_input=_formatter_input(worker="Required MCP capability is unavailable."),
        task_kind="knowledge_request",
        selected_strategy="retrieve_then_reason",
        worker_confidence=0.0,
    )
    assert result is None

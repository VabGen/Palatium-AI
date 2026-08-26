"""Quality HITL reject → revision loop (no phrase hardcoding)."""

from __future__ import annotations

from types import SimpleNamespace
from typing import Any, cast
from unittest.mock import AsyncMock, MagicMock

import pytest

from palatium_ai.application.services.cost_budget import CostBudgetService
from palatium_ai.application.services.intent_service import _MAX_QUALITY_REVISIONS, IntentService
from palatium_ai.application.services.kill_switch import KillSwitchService
from palatium_ai.domain.agents.formatter import FormatterTaskResult
from palatium_ai.domain.content import ContentDocument, DocumentMeta, HeadingBlock
from palatium_ai.domain.hitl.cards import default_review_options


def _doc(*, title: str = "Revised") -> ContentDocument:
    return ContentDocument(
        schema_version=1,
        locale="ru-RU",
        title=title,
        blocks=(HeadingBlock(type="heading", level=2, text=title, icon=None),),
        actions=(),
        meta=DocumentMeta(confidence=0.9, requires_review=False, source_refs=()),
    )


def test_quality_reject_option_is_revise_labeled() -> None:
    reject = next(opt for opt in default_review_options() if opt.action_id == "reject")
    assert "revise" in reject.label.lower()


@pytest.mark.asyncio
async def test_revise_after_quality_reject_passes_feedback_to_graph() -> None:
    captured: dict[str, Any] = {}

    async def fake_ainvoke(graph_input: object, config: object = None) -> dict[str, object]:
        _ = config
        captured["input"] = graph_input
        return {
            "formatted": FormatterTaskResult(
                task_id="t-rev1",
                agent_role="formatter",
                status="success",
                confidence=0.9,
                requires_review=False,
                output=_doc(),
            ),
            "effective_user_text": "analyze the claim",
        }

    graph = MagicMock()
    graph.ainvoke = AsyncMock(side_effect=fake_ainvoke)
    session_service = MagicMock()
    session_service.get_session = AsyncMock(
        return_value=SimpleNamespace(
            context={
                "effective_user_text": "analyze the claim",
                "last_critic_summary": "Answer ignored prior user document",
                "quality_revision_count": "0",
            }
        )
    )
    session_service.touch_session = AsyncMock()
    session_service.assert_thread_access = AsyncMock()
    hitl_service = MagicMock()
    hitl_service.create_review_card = AsyncMock()

    service = IntentService(
        cast("Any", graph),
        session_service=session_service,
        hitl_service=hitl_service,
        kill_switch=KillSwitchService(),
        cost_budget=CostBudgetService(turn_budget_usd=0.0, daily_budget_usd=0.0),
        dialog_turn_store=None,
    )
    result = await service.revise_after_quality_reject(
        thread_id="thread-1",
        task_id="task-1",
        user_id="u1",
    )
    assert result.status == "success"
    assert result.output is not None
    graph_input = captured["input"]
    assert isinstance(graph_input, dict)
    assert graph_input["revision_feedback"] == "Answer ignored prior user document"
    assert graph_input["user_text"] == "analyze the claim"


@pytest.mark.asyncio
async def test_revise_prefers_dialog_turn_over_context_preview() -> None:
    """Full utterance lives in DialogTurnStore; session.context may hold only a preview."""
    from palatium_ai.domain.memory.turns import DialogTurn, DialogTurnWindow
    from palatium_ai.domain.sessions.context_privacy import session_user_text_preview

    full = "A" * 400
    preview = session_user_text_preview(full)
    assert preview != full

    captured: dict[str, Any] = {}

    async def fake_ainvoke(graph_input: object, config: object = None) -> dict[str, object]:
        _ = config
        captured["input"] = graph_input
        return {
            "formatted": FormatterTaskResult(
                task_id="t-rev1",
                agent_role="formatter",
                status="success",
                confidence=0.9,
                requires_review=False,
                output=_doc(),
            ),
        }

    graph = MagicMock()
    graph.ainvoke = AsyncMock(side_effect=fake_ainvoke)
    session_service = MagicMock()
    session_service.get_session = AsyncMock(
        return_value=SimpleNamespace(
            context={
                "effective_user_text": preview,
                "last_user_text": preview,
                "quality_revision_count": "0",
            }
        )
    )
    session_service.touch_session = AsyncMock()
    session_service.assert_thread_access = AsyncMock()

    dialog_store = MagicMock()
    dialog_store.list_recent_turns = AsyncMock(
        return_value=DialogTurnWindow(
            thread_id="thread-1",
            turns=(DialogTurn(thread_id="thread-1", role="user", content=full, seq=0),),
            limit=12,
        )
    )
    dialog_store.append_turn = AsyncMock()

    service = IntentService(
        cast("Any", graph),
        session_service=session_service,
        hitl_service=MagicMock(),
        kill_switch=KillSwitchService(),
        cost_budget=CostBudgetService(turn_budget_usd=0.0, daily_budget_usd=0.0),
        dialog_turn_store=dialog_store,
    )
    result = await service.revise_after_quality_reject(thread_id="thread-1", task_id="task-1")
    assert result.status == "success"
    graph_input = captured["input"]
    assert isinstance(graph_input, dict)
    assert graph_input["user_text"] == full


@pytest.mark.asyncio
async def test_revise_after_quality_reject_respects_limit() -> None:
    graph = MagicMock()
    graph.ainvoke = AsyncMock()
    session_service = MagicMock()
    session_service.get_session = AsyncMock(
        return_value=SimpleNamespace(
            context={
                "effective_user_text": "claim text",
                "quality_revision_count": str(_MAX_QUALITY_REVISIONS),
            }
        )
    )
    session_service.touch_session = AsyncMock()
    session_service.assert_thread_access = AsyncMock()
    service = IntentService(
        cast("Any", graph),
        session_service=session_service,
        hitl_service=MagicMock(),
        kill_switch=KillSwitchService(),
        cost_budget=CostBudgetService(),
    )
    result = await service.revise_after_quality_reject(thread_id="t1", task_id="task-1")
    assert result.status == "failure"
    assert result.error is not None
    assert "limit" in result.error.lower()
    graph.ainvoke.assert_not_called()

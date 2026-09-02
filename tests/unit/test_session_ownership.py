"""Session ownership policy — mutate path must not steal bound threads."""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest

from pydantic import ValidationError

from palatium_ai.application.services.intent_service import IntentService
from palatium_ai.domain.content import WidgetBlock
from palatium_ai.domain.sessions.errors import SessionOwnershipError
from palatium_ai.domain.sessions.ownership import evaluate_session_access, next_session_owner


def test_evaluate_session_access_denies_foreign_owner() -> None:
    allowed = evaluate_session_access(
        owner_user_id="user-owner",
        caller_user_id="user-attacker",
        session_exists=True,
    )
    assert not allowed.allowed
    admin = evaluate_session_access(
        owner_user_id="user-owner",
        caller_user_id="ops",
        is_admin=True,
        session_exists=True,
    )
    assert admin.allowed


def test_evaluate_session_access_unowned_never_claimable() -> None:
    read = evaluate_session_access(
        owner_user_id=None,
        caller_user_id="user-a",
        session_exists=True,
    )
    assert not read.allowed
    assert read.reason == "unowned_not_readable"
    # allow_claim must not transfer residual MCP/dialog payloads to a stranger.
    mutate = evaluate_session_access(
        owner_user_id=None,
        caller_user_id="user-a",
        session_exists=True,
        allow_claim=True,
    )
    assert not mutate.allowed
    assert mutate.reason == "unowned_not_readable"
    admin = evaluate_session_access(
        owner_user_id=None,
        caller_user_id="ops",
        is_admin=True,
        session_exists=True,
    )
    assert admin.allowed


def test_evaluate_session_access_missing_thread() -> None:
    create = evaluate_session_access(
        owner_user_id=None,
        caller_user_id="user-a",
        allow_missing=True,
        session_exists=False,
    )
    assert create.allowed
    missing = evaluate_session_access(
        owner_user_id=None,
        caller_user_id="user-a",
        allow_missing=False,
        session_exists=False,
    )
    assert not missing.allowed


def test_next_session_owner_never_overwrites_bound_user() -> None:
    assert next_session_owner(existing_owner=None, incoming_user_id="u1") == "u1"
    assert next_session_owner(existing_owner="u1", incoming_user_id="u1") == "u1"
    assert next_session_owner(existing_owner="u1", incoming_user_id=None) == "u1"
    with pytest.raises(SessionOwnershipError):
        next_session_owner(existing_owner="u1", incoming_user_id="u2")


def test_widget_href_rejects_javascript_and_relative() -> None:
    ok = WidgetBlock(kind="edms_doc", ref_id="1", href="https://next.edo.iba/doc/1")
    assert ok.href == "https://next.edo.iba/doc/1"
    with pytest.raises(ValidationError):
        WidgetBlock(kind="edms_doc", ref_id="1", href="javascript:alert(1)")
    with pytest.raises(ValidationError):
        WidgetBlock(kind="edms_doc", ref_id="1", href="/internal")
    with pytest.raises(ValidationError):
        WidgetBlock(kind="edms_doc", ref_id="1", href="data:text/html,x")


@pytest.mark.asyncio
async def test_intent_process_rejects_foreign_thread_before_graph() -> None:
    session_service = SimpleNamespace(
        get_session=AsyncMock(
            return_value=SimpleNamespace(user_id="user-owner", thread_id="thread-secret"),
        ),
        touch_session=AsyncMock(),
        assert_thread_access=AsyncMock(side_effect=SessionOwnershipError("Not allowed")),
    )
    graph = MagicMock()
    graph.ainvoke = AsyncMock()
    service = IntentService(
        graph,  # type: ignore[arg-type]
        session_service=session_service,  # type: ignore[arg-type]
        hitl_service=MagicMock(),
    )
    with pytest.raises(SessionOwnershipError):
        await service.process(text="hi", thread_id="thread-secret", user_id="user-attacker")
    graph.ainvoke.assert_not_called()
    session_service.touch_session.assert_not_called()

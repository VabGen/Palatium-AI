# tests/integration/test_memory_hitl_e2e.py

"""E2E: save → HITL approve → search_memory → forget → HITL approve → empty search."""

from __future__ import annotations

import json

from unittest.mock import AsyncMock

import pytest

from palatium_ai.application.services.hitl_respond_facade import HitlRespondFacade
from palatium_ai.domain.hitl.cards import HITLResolveRequest
from tests.conftest import make_memory_hitl_stack

_HITL_HMAC_ACTOR = "user-mem-e2e"
_ORG = "org-mem-e2e"
_THREAD = "thread-mem-e2e"
_ENTRY_KEY = "pref-agenda-format"


def _action_request(card: object, *, action_id: str, idempotency_key: str) -> HITLResolveRequest:
    option = next(opt for opt in card.options if opt.action_id == action_id)  # type: ignore[attr-defined]
    return HITLResolveRequest(
        action_id=action_id,
        action_token=option.action_token,
        idempotency_key=idempotency_key,
    )


@pytest.mark.integration
@pytest.mark.asyncio
async def test_memory_save_approve_search_then_forget_approve() -> None:
    save, forget, _port, hitl, handler = make_memory_hitl_stack()
    intent = AsyncMock()
    facade = HitlRespondFacade(
        hitl_service=hitl,
        intent_service=intent,
        memory_save_service=save,  # type: ignore[arg-type]
        memory_forget_service=forget,  # type: ignore[arg-type]
    )

    save_card = await save.request_save(  # type: ignore[attr-defined]
        thread_id=_THREAD,
        owner_user_id=_HITL_HMAC_ACTOR,
        org_id=_ORG,
        namespace_kind="user",
        scope_id=_HITL_HMAC_ACTOR,
        entry_key=_ENTRY_KEY,
        text="User prefers agenda tables with time column.",
        memory_type="preference",
    )
    assert save_card.task_id.startswith("mem-save-")

    # Not visible until approve
    before = await handler.call_tool(  # type: ignore[attr-defined]
        "search_memory",
        {"user_id": _HITL_HMAC_ACTOR, "query": "agenda tables", "limit": "5"},
    )
    assert json.loads(before.content[0]["text"])["hit_count"] == 0

    save_outcome = await facade.respond(
        save_card.card_id,
        _action_request(save_card, action_id="approve", idempotency_key="mem-e2e-save-approve"),
        actor_subject=_HITL_HMAC_ACTOR,
        actor_org_id=_ORG,
        is_admin=False,
    )
    assert save_outcome.resumed is None
    intent.resume_after_tool_approval.assert_not_awaited()

    after_save = await handler.call_tool(  # type: ignore[attr-defined]
        "search_memory",
        {"user_id": _HITL_HMAC_ACTOR, "query": "agenda tables", "limit": "5"},
    )
    save_payload = json.loads(after_save.content[0]["text"])
    assert save_payload["hit_count"] >= 1
    assert "tables" in save_payload["hits"][0]["text"].lower()

    forget_card = await forget.request_forget(  # type: ignore[attr-defined]
        thread_id=_THREAD,
        owner_user_id=_HITL_HMAC_ACTOR,
        org_id=_ORG,
        namespace_kind="user",
        scope_id=_HITL_HMAC_ACTOR,
        entry_key=_ENTRY_KEY,
    )
    assert forget_card.task_id.startswith("mem-forget-")

    # Still present until forget approve
    mid = await handler.call_tool(  # type: ignore[attr-defined]
        "search_memory",
        {"user_id": _HITL_HMAC_ACTOR, "query": "agenda tables", "limit": "5"},
    )
    assert json.loads(mid.content[0]["text"])["hit_count"] >= 1

    forget_outcome = await facade.respond(
        forget_card.card_id,
        _action_request(forget_card, action_id="approve", idempotency_key="mem-e2e-forget-approve"),
        actor_subject=_HITL_HMAC_ACTOR,
        actor_org_id=_ORG,
        is_admin=False,
    )
    assert forget_outcome.resumed is None

    after_forget = await handler.call_tool(  # type: ignore[attr-defined]
        "search_memory",
        {"user_id": _HITL_HMAC_ACTOR, "query": "agenda tables", "limit": "5"},
    )
    assert json.loads(after_forget.content[0]["text"])["hit_count"] == 0


@pytest.mark.integration
@pytest.mark.asyncio
async def test_memory_save_reject_skips_write() -> None:
    save, _forget, _port, hitl, handler = make_memory_hitl_stack()
    intent = AsyncMock()
    facade = HitlRespondFacade(
        hitl_service=hitl,
        intent_service=intent,
        memory_save_service=save,  # type: ignore[arg-type]
    )

    card = await save.request_save(  # type: ignore[attr-defined]
        thread_id=_THREAD,
        owner_user_id=_HITL_HMAC_ACTOR,
        org_id=_ORG,
        namespace_kind="user",
        scope_id=_HITL_HMAC_ACTOR,
        entry_key="should-not-persist",
        text="Rejected preference must not land in memory.",
        memory_type="preference",
    )
    await facade.respond(
        card.card_id,
        _action_request(card, action_id="reject", idempotency_key="mem-e2e-save-reject"),
        actor_subject=_HITL_HMAC_ACTOR,
        actor_org_id=_ORG,
        is_admin=False,
    )

    search = await handler.call_tool(  # type: ignore[attr-defined]
        "search_memory",
        {"user_id": _HITL_HMAC_ACTOR, "query": "Rejected preference", "limit": "5"},
    )
    assert json.loads(search.content[0]["text"])["hit_count"] == 0

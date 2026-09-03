# tests/integration/test_memory_consolidate_hitl_e2e.py

"""E2E: consolidate HITL approve → worker → search_memory; reject skips enqueue."""

from __future__ import annotations

import asyncio
import json

from unittest.mock import AsyncMock

import pytest

from palatium_ai.application.services.hitl_respond_facade import HitlRespondFacade
from palatium_ai.domain.hitl.cards import HITLResolveRequest
from tests.conftest import make_memory_consolidate_hitl_stack

_HITL_HMAC_ACTOR = "user-consol-e2e"
_ORG = "org-consol-e2e"
_THREAD = "thread-consol-e2e"

_KEEPER_PAYLOAD = json.dumps(
    {
        "facts": [
            {
                "text": "User prefers meeting agendas as tables",
                "kind": "preference",
                "confidence": 0.9,
                "key_hint": "pref-tables",
            }
        ],
        "reasoning": "stable preference from dialog",
    }
)


def _action_request(card: object, *, action_id: str, idempotency_key: str) -> HITLResolveRequest:
    option = next(opt for opt in card.options if opt.action_id == action_id)  # type: ignore[attr-defined]
    return HITLResolveRequest(
        action_id=action_id,
        action_token=option.action_token,
        idempotency_key=idempotency_key,
    )


@pytest.mark.integration
@pytest.mark.asyncio
async def test_memory_consolidate_approve_runs_worker_then_search() -> None:
    consolidate, consolidation, _port, hitl, handler, _dialog = make_memory_consolidate_hitl_stack(
        llm_content=_KEEPER_PAYLOAD,
    )
    intent = AsyncMock()
    facade = HitlRespondFacade(
        hitl_service=hitl,
        intent_service=intent,
        memory_consolidate_service=consolidate,  # type: ignore[arg-type]
    )

    before = await handler.call_tool(  # type: ignore[attr-defined]
        "search_memory",
        {"user_id": _HITL_HMAC_ACTOR, "query": "agendas tables", "limit": "5"},
    )
    assert json.loads(before.content[0]["text"])["hit_count"] == 0

    worker = asyncio.create_task(consolidation.run_worker())  # type: ignore[attr-defined]
    try:
        card = await consolidate.request_consolidate(  # type: ignore[attr-defined]
            thread_id=_THREAD,
            owner_user_id=_HITL_HMAC_ACTOR,
            org_id=_ORG,
            consolidate_task_id="job-consol-e2e",
        )
        assert card.task_id.startswith("mem-consolidate-")

        outcome = await facade.respond(
            card.card_id,
            _action_request(card, action_id="approve", idempotency_key="consol-e2e-approve"),
            actor_subject=_HITL_HMAC_ACTOR,
            actor_org_id=_ORG,
            is_admin=False,
        )
        assert outcome.resumed is None
        intent.resume_after_tool_approval.assert_not_awaited()

        payload: dict[str, object] = {"hit_count": 0}
        for _ in range(25):
            after = await handler.call_tool(  # type: ignore[attr-defined]
                "search_memory",
                {"user_id": _HITL_HMAC_ACTOR, "query": "agendas tables", "limit": "5"},
            )
            payload = json.loads(after.content[0]["text"])
            if int(payload.get("hit_count", 0)) >= 1:
                break
            await asyncio.sleep(0.02)

        assert int(payload["hit_count"]) >= 1
        hits = payload["hits"]
        assert isinstance(hits, list) and hits
        assert "tables" in str(hits[0]["text"]).lower()
    finally:
        await consolidation.stop()  # type: ignore[attr-defined]
        await worker


@pytest.mark.integration
@pytest.mark.asyncio
async def test_memory_consolidate_reject_skips_worker() -> None:
    consolidate, consolidation, _port, hitl, handler, _dialog = make_memory_consolidate_hitl_stack(
        llm_content=_KEEPER_PAYLOAD,
    )
    intent = AsyncMock()
    facade = HitlRespondFacade(
        hitl_service=hitl,
        intent_service=intent,
        memory_consolidate_service=consolidate,  # type: ignore[arg-type]
    )

    worker = asyncio.create_task(consolidation.run_worker())  # type: ignore[attr-defined]
    try:
        card = await consolidate.request_consolidate(  # type: ignore[attr-defined]
            thread_id=_THREAD,
            owner_user_id=_HITL_HMAC_ACTOR,
            org_id=_ORG,
        )
        await facade.respond(
            card.card_id,
            _action_request(card, action_id="reject", idempotency_key="consol-e2e-reject"),
            actor_subject=_HITL_HMAC_ACTOR,
            actor_org_id=_ORG,
            is_admin=False,
        )
        await asyncio.sleep(0.05)

        search = await handler.call_tool(  # type: ignore[attr-defined]
            "search_memory",
            {"user_id": _HITL_HMAC_ACTOR, "query": "agendas tables", "limit": "5"},
        )
        assert json.loads(search.content[0]["text"])["hit_count"] == 0
    finally:
        await consolidation.stop()  # type: ignore[attr-defined]
        await worker

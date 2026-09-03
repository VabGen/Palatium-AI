# tests/integration/test_document_ingest_e2e.py

"""E2E: prepare → HITL commit → approve → knowledge write → search_knowledge."""

from __future__ import annotations

from unittest.mock import AsyncMock

import pytest

from palatium_ai.application.services.hitl_respond_facade import HitlRespondFacade
from palatium_ai.domain.hitl.cards import HITLResolveRequest
from palatium_ai.domain.knowledge.types import SearchKnowledgeQuery
from tests.conftest import make_document_ingest_stack

_HITL_HMAC_ACTOR = "user-e2e"


def _approve_request(card: object) -> HITLResolveRequest:
    option = next(opt for opt in card.options if opt.action_id == "approve")  # type: ignore[attr-defined]
    return HITLResolveRequest(
        action_id="approve",
        action_token=option.action_token,
        idempotency_key="doc-ingest-e2e-approve",
    )


@pytest.mark.integration
@pytest.mark.asyncio
async def test_document_ingest_hitl_approve_then_search_knowledge() -> None:
    ingest, knowledge, hitl, _handler = make_document_ingest_stack()
    intent = AsyncMock()
    facade = HitlRespondFacade(
        hitl_service=hitl,
        intent_service=intent,
        document_ingest_service=ingest,
    )

    prepare = await ingest.prepare_chunks(  # type: ignore[attr-defined]
        task_id="prep-e2e-1",
        thread_id="thread-e2e",
        raw_text="Security policy: rotate passwords every 90 days.\n\nUse MFA for admin accounts.",
        document_title="Security Handbook",
    )
    assert prepare.status == "success"
    assert prepare.output is not None
    assert len(prepare.output.chunks) >= 2

    card = await ingest.request_commit(  # type: ignore[attr-defined]
        prepare_task_id="prep-e2e-1",
        owner_user_id=_HITL_HMAC_ACTOR,
        org_id="org-e2e",
    )
    assert card.task_id.startswith("doc-ingest-")

    outcome = await facade.respond(
        card.card_id,
        _approve_request(card),
        actor_subject=_HITL_HMAC_ACTOR,
        actor_org_id="org-e2e",
        is_admin=False,
    )
    assert outcome.resumed is None
    intent.resume_after_tool_approval.assert_not_awaited()
    assert len(knowledge.documents) == 1  # type: ignore[attr-defined]

    search = await knowledge.search_knowledge(  # type: ignore[attr-defined]
        SearchKnowledgeQuery(
            user_id=_HITL_HMAC_ACTOR,
            query="password rotation MFA",
            thread_id="thread-e2e",
            limit=5,
        )
    )
    assert len(search.hits) >= 1
    assert any("password" in hit.text.lower() for hit in search.hits)
    assert search.hits[0].document_title == "Security Handbook"


@pytest.mark.integration
@pytest.mark.asyncio
async def test_document_ingest_hitl_reject_skips_knowledge_write() -> None:
    ingest, knowledge, hitl, _handler = make_document_ingest_stack()
    intent = AsyncMock()
    facade = HitlRespondFacade(
        hitl_service=hitl,
        intent_service=intent,
        document_ingest_service=ingest,
    )

    await ingest.prepare_chunks(  # type: ignore[attr-defined]
        task_id="prep-reject",
        thread_id="thread-reject",
        raw_text="Draft content only.",
    )
    card = await ingest.request_commit(  # type: ignore[attr-defined]
        prepare_task_id="prep-reject",
        owner_user_id=_HITL_HMAC_ACTOR,
        org_id="org-e2e",
    )
    reject = next(opt for opt in card.options if opt.action_id == "reject")
    await facade.respond(
        card.card_id,
        HITLResolveRequest(
            action_id="reject",
            action_token=reject.action_token,
            idempotency_key="doc-ingest-e2e-reject",
        ),
        actor_subject=_HITL_HMAC_ACTOR,
        actor_org_id="org-e2e",
        is_admin=False,
    )

    assert len(knowledge.documents) == 0  # type: ignore[attr-defined]
    search = await knowledge.search_knowledge(  # type: ignore[attr-defined]
        SearchKnowledgeQuery(user_id=_HITL_HMAC_ACTOR, query="Draft", thread_id="thread-reject")
    )
    assert search.hits == ()

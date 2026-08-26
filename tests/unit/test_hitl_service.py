"""HITL card lifecycle: create, resolve, idempotency, expiry, action tokens v2."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from palatium_ai.application.services.hitl_service import (
    HitlCardConflictError,
    HitlCardGoneError,
    HitlInvalidActionError,
    HitlService,
)
from palatium_ai.domain.content import ActionSpec, ContentDocument, DocumentMeta, HeadingBlock
from palatium_ai.domain.hitl.cards import HITLResolveRequest, clamp_ttl_seconds
from palatium_ai.domain.hitl.risk_policy import HitlRiskPolicy
from palatium_ai.infrastructure.hitl.memory_store import InMemoryHitlCardStore

HITL_TEST_HMAC = "unit-test-hitl-hmac-key-32bytes!!"  # noqa: S105
ACTOR = "user-owner"


def _document() -> ContentDocument:
    return ContentDocument(
        schema_version=1,
        locale="en-US",
        title="Needs review",
        blocks=(HeadingBlock(type="heading", level=2, text="Needs review", icon=None),),
        actions=(),
        meta=DocumentMeta(confidence=0.4, requires_review=True, source_refs=()),
    )


def _service(store: InMemoryHitlCardStore | None = None) -> HitlService:
    return HitlService(
        store or InMemoryHitlCardStore(),
        signing_secret=HITL_TEST_HMAC,
        manager_roles=frozenset({"manager", "admin"}),
    )


def _resolve(card, *, action_id: str = "approve", idem: str = "idem-00123456") -> HITLResolveRequest:
    option = next(opt for opt in card.options if opt.action_id == action_id)
    return HITLResolveRequest(
        action_id=action_id,
        action_token=option.action_token,
        idempotency_key=idem,
    )


async def _do_resolve(service: HitlService, card, body: HITLResolveRequest, *, actor: str = ACTOR):
    return await service.resolve(card.card_id, body, actor_subject=actor)


@pytest.mark.asyncio
async def test_create_and_resolve_card() -> None:
    service = _service()
    card = await service.create_review_card(
        thread_id="t1",
        task_id="task-1",
        document=_document(),
        confidence=0.4,
        owner_user_id=ACTOR,
        org_id="org-1",
    )
    assert card.status == "pending"
    assert len(card.options) == 2
    assert all(len(opt.action_token) >= 32 for opt in card.options)
    assert card.risk_score == pytest.approx(0.6)
    assert card.token_nonce
    assert card.owner_user_id == ACTOR

    result = await _do_resolve(service, card, _resolve(card))
    assert result.replayed is False
    assert result.card.status == "resolved"
    assert result.card.resolved_action_id == "approve"
    assert all(opt.action_token == "" for opt in result.card.options)


@pytest.mark.asyncio
async def test_idempotent_replay() -> None:
    service = _service()
    card = await service.create_review_card(
        thread_id="t1",
        task_id="task-1",
        document=_document(),
        confidence=0.3,
        owner_user_id=ACTOR,
    )
    body = _resolve(card, action_id="reject", idem="idem-replay-01")
    first = await _do_resolve(service, card, body)
    second = await _do_resolve(service, card, body)
    assert first.replayed is False
    assert second.replayed is True
    assert second.card.resolved_action_id == "reject"


@pytest.mark.asyncio
async def test_one_time_token_consume_rejects_replay_with_old_token() -> None:
    service = _service()
    card = await service.create_review_card(
        thread_id="t1",
        task_id="task-1",
        document=_document(),
        confidence=0.3,
        owner_user_id=ACTOR,
    )
    body = _resolve(card, action_id="approve", idem="idem-once-0001")
    await _do_resolve(service, card, body)
    with pytest.raises(HitlCardConflictError):
        await _do_resolve(
            service,
            card,
            HITLResolveRequest(
                action_id="approve",
                action_token=body.action_token,
                idempotency_key="idem-once-0002",
            ),
        )


@pytest.mark.asyncio
async def test_subject_mismatch_rejected() -> None:
    service = _service()
    card = await service.create_review_card(
        thread_id="t1",
        task_id="task-1",
        document=_document(),
        confidence=0.3,
        owner_user_id=ACTOR,
    )
    with pytest.raises(HitlInvalidActionError, match="subject mismatch"):
        await service.resolve(card.card_id, _resolve(card), actor_subject="user-attacker")


@pytest.mark.asyncio
async def test_concurrent_resolve_second_loses_cas() -> None:
    store = InMemoryHitlCardStore()
    service = _service(store)
    card = await service.create_review_card(
        thread_id="t1",
        task_id="task-1",
        document=_document(),
        confidence=0.3,
        owner_user_id=ACTOR,
    )
    approve = _resolve(card, action_id="approve", idem="idem-approve-1")
    reject = _resolve(card, action_id="reject", idem="idem-reject-2")
    first = await _do_resolve(service, card, approve)
    assert first.replayed is False
    with pytest.raises(HitlCardConflictError):
        await _do_resolve(service, card, reject)
    stored = await store.get(card.card_id)
    assert stored is not None
    assert stored.resolved_action_id == "approve"


@pytest.mark.asyncio
async def test_invalid_action_rejected() -> None:
    service = _service()
    card = await service.create_review_card(
        thread_id="t1",
        task_id="task-1",
        document=_document(),
        confidence=0.3,
        owner_user_id=ACTOR,
    )
    with pytest.raises(HitlInvalidActionError):
        await service.resolve(
            card.card_id,
            HITLResolveRequest(
                action_id="hack",
                action_token="0" * 64,
                idempotency_key="idem-hack-0001",
            ),
            actor_subject=ACTOR,
        )


@pytest.mark.asyncio
async def test_forged_action_token_rejected() -> None:
    service = _service()
    card = await service.create_review_card(
        thread_id="t1",
        task_id="task-1",
        document=_document(),
        confidence=0.3,
        owner_user_id=ACTOR,
    )
    with pytest.raises(HitlInvalidActionError, match="action_token"):
        await service.resolve(
            card.card_id,
            HITLResolveRequest(
                action_id="approve",
                action_token="a" * 64,
                idempotency_key="idem-forge-0001",
            ),
            actor_subject=ACTOR,
        )


@pytest.mark.asyncio
async def test_expired_high_risk_escalates() -> None:
    store = InMemoryHitlCardStore()
    service = _service(store)
    card = await service.create_review_card(
        thread_id="t1",
        task_id="task-1",
        document=_document(),
        confidence=0.2,
        owner_user_id=ACTOR,
        org_id="org-1",
    )
    expired = card.model_copy(update={"expires_at": datetime.now(UTC) - timedelta(seconds=1)})
    await store.save(expired)

    with pytest.raises(HitlCardGoneError):
        await _do_resolve(service, card, _resolve(card, idem="idem-late-0001"))

    closed = await service.get_card(card.card_id)
    assert closed is not None
    assert closed.status == "escalated"
    assert closed.escalate_to_roles == ("admin", "manager")
    assert closed.token_nonce != card.token_nonce
    assert all(len(opt.action_token) >= 32 for opt in closed.options)


@pytest.mark.asyncio
async def test_sweep_expired_escalates_high_risk_tenant_queue() -> None:
    store = InMemoryHitlCardStore()
    service = _service(store)
    card_a = await service.create_review_card(
        thread_id="t1",
        task_id="task-1",
        document=_document(),
        confidence=0.2,
        owner_user_id=ACTOR,
        org_id="org-a",
    )
    card_b = await service.create_review_card(
        thread_id="t2",
        task_id="task-2",
        document=_document(),
        confidence=0.2,
        owner_user_id=ACTOR,
        org_id="org-b",
    )
    for card in (card_a, card_b):
        expired = card.model_copy(update={"expires_at": datetime.now(UTC) - timedelta(seconds=1)})
        await store.save(expired)

    stats = await service.sweep_expired()
    assert stats["escalated"] == 2
    all_queue = await service.list_escalated()
    assert len(all_queue) == 2
    assert all(opt.action_token == "" for card in all_queue for opt in card.options)

    scoped = await service.list_escalated(org_id="org-a")
    assert len(scoped) == 1
    assert scoped[0].card_id == card_a.card_id
    assert scoped[0].org_id == "org-a"


@pytest.mark.asyncio
async def test_sweep_dead_letters_expired_escalated() -> None:
    store = InMemoryHitlCardStore()
    service = _service(store)
    card = await service.create_tool_approval_card(
        thread_id="t-dl",
        task_id="task-dl",
        server_name="edms",
        tool_name="archive_document",
        side_effect="write",
        risk_score=0.85,
        argument_preview="document_id=DOC-1",
        owner_user_id=ACTOR,
        org_id="org-1",
    )
    expired_pending = card.model_copy(update={"expires_at": datetime.now(UTC) - timedelta(seconds=1)})
    await store.save(expired_pending)
    first = await service.sweep_expired()
    assert first["escalated"] == 1
    escalated = await store.get(card.card_id)
    assert escalated is not None
    assert escalated.status == "escalated"
    past_manager = escalated.model_copy(update={"expires_at": datetime.now(UTC) - timedelta(seconds=1)})
    await store.save(past_manager)
    second = await service.sweep_expired()
    assert second["dead_letter"] == 1
    closed = await store.get(card.card_id)
    assert closed is not None
    assert closed.status == "dead_letter"
    assert await service.list_escalated(org_id="org-1") == []


@pytest.mark.asyncio
async def test_get_card_lazily_dead_letters_expired_escalated() -> None:
    store = InMemoryHitlCardStore()
    service = _service(store)
    card = await service.create_tool_approval_card(
        thread_id="t-lazy",
        task_id="task-lazy",
        server_name="edms",
        tool_name="archive_document",
        side_effect="write",
        risk_score=0.9,
        argument_preview="document_id=DOC-L",
        owner_user_id=ACTOR,
        org_id="org-1",
    )
    await store.save(card.model_copy(update={"expires_at": datetime.now(UTC) - timedelta(seconds=1)}))
    await service.sweep_expired()
    escalated = await store.get(card.card_id)
    assert escalated is not None and escalated.status == "escalated"
    await store.save(escalated.model_copy(update={"expires_at": datetime.now(UTC) - timedelta(seconds=1)}))
    viewed = await service.get_card(card.card_id)
    assert viewed is not None
    assert viewed.status == "dead_letter"
    assert await service.list_escalated(org_id="org-1") == []


@pytest.mark.asyncio
async def test_expire_cas_does_not_overwrite_resolved() -> None:
    """Sweep must not flip a card that resolved between read and expire write."""
    store = InMemoryHitlCardStore()
    service = _service(store)
    card = await service.create_review_card(
        thread_id="t1",
        task_id="task-1",
        document=_document(),
        confidence=0.2,
        owner_user_id=ACTOR,
    )
    await _do_resolve(service, card, _resolve(card, idem="idem-race-win"))
    stale = card.model_copy(update={"expires_at": datetime.now(UTC) - timedelta(seconds=1)})
    closed = await service._expire_card(stale, now=datetime.now(UTC))
    assert closed.status == "resolved"
    assert closed.resolved_action_id == "approve"
    stored = await store.get(card.card_id)
    assert stored is not None
    assert stored.status == "resolved"


@pytest.mark.asyncio
async def test_manager_resolve_escalated_mcp_card() -> None:
    store = InMemoryHitlCardStore()
    service = _service(store)
    card = await service.create_tool_approval_card(
        thread_id="t1",
        task_id="task-1",
        server_name="edms",
        tool_name="search_documents",
        side_effect="write",
        risk_score=0.9,
        argument_preview="q=test",
        owner_user_id=ACTOR,
        org_id="org-1",
    )
    expired = card.model_copy(update={"expires_at": datetime.now(UTC) - timedelta(seconds=1)})
    await store.save(expired)
    with pytest.raises(HitlCardGoneError):
        await _do_resolve(service, card, _resolve(card, action_id="approve", idem="idem-user-late"))
    escalated = await service.get_card(card.card_id)
    assert escalated is not None
    assert escalated.status == "escalated"
    option = next(opt for opt in escalated.options if opt.action_id == "approve")
    result = await service.resolve_escalated(
        escalated.card_id,
        HITLResolveRequest(
            action_id="approve",
            action_token=option.action_token,
            idempotency_key="idem-mgr-0001",
        ),
        actor_subject="manager-1",
    )
    assert result.card.status == "resolved"
    assert result.card.resolved_action_id == "approve"


@pytest.mark.asyncio
async def test_create_choice_card_stamps_tokens_and_risk_floor() -> None:
    service = _service()
    card = await service.create_choice_card(
        thread_id="t1",
        task_id="task-1",
        title="Analysis type",
        body="Select one",
        actions=(
            ActionSpec(action_id="risk", label="Risk Analysis", kind="custom", style="primary"),
            ActionSpec(action_id="compliance", label="Compliance", kind="custom", style="secondary"),
        ),
        owner_user_id=ACTOR,
    )
    assert card.purpose == "user_choice"
    assert len(card.options) == 2
    assert all(len(opt.action_token) >= 32 for opt in card.options)
    assert card.risk_score == pytest.approx(HitlRiskPolicy.CHOICE_FLOOR)
    result = await _do_resolve(service, card, _resolve(card, action_id="risk", idem="idem-choice-01"))
    assert result.card.resolved_action_id == "risk"


def test_risk_policy_confirm_floor() -> None:
    actions = (
        ActionSpec(action_id="approve", label="Approve", kind="approve", style="primary"),
        ActionSpec(action_id="reject", label="Reject", kind="reject", style="danger"),
    )
    assert HitlRiskPolicy.for_choice(actions) == pytest.approx(HitlRiskPolicy.CONFIRM_FLOOR)


@pytest.mark.asyncio
async def test_quality_review_stores_content_sha256() -> None:
    service = _service()
    card = await service.create_review_card(
        thread_id="t1",
        task_id="task-1",
        document=_document(),
        confidence=0.4,
        owner_user_id=ACTOR,
    )
    assert card.content_sha256
    assert len(card.content_sha256) == 64


@pytest.mark.asyncio
async def test_forge_records_deny_metric() -> None:
    from palatium_ai.core.observability.metrics import agent_metrics

    before = agent_metrics.hitl_deny_count("forge")
    service = _service()
    card = await service.create_review_card(
        thread_id="t1",
        task_id="task-1",
        document=_document(),
        confidence=0.3,
        owner_user_id=ACTOR,
    )
    with pytest.raises(HitlInvalidActionError, match="action_token"):
        await service.resolve(
            card.card_id,
            HITLResolveRequest(
                action_id="approve",
                action_token="a" * 64,
                idempotency_key="idem-forge-metric",
            ),
            actor_subject=ACTOR,
        )
    assert agent_metrics.hitl_deny_count("forge") == before + 1


@pytest.mark.asyncio
async def test_step_up_challenge_issues_assertion_when_enforced() -> None:
    service = HitlService(
        InMemoryHitlCardStore(),
        signing_secret=HITL_TEST_HMAC,
        manager_roles=frozenset({"manager"}),
        step_up_required=True,
    )
    card = await service.create_tool_approval_card(
        thread_id="t1",
        task_id="task-1",
        server_name="edms",
        tool_name="write_doc",
        side_effect="write",
        risk_score=0.9,
        argument_preview="x=1",
        owner_user_id=ACTOR,
    )
    challenge = await service.issue_step_up_challenge(card.card_id, actor_subject=ACTOR)
    assert challenge.required is True
    assert challenge.method == "hmac_stub"
    assert challenge.assertion
    skipped = HitlService(
        InMemoryHitlCardStore(),
        signing_secret=HITL_TEST_HMAC,
        step_up_required=False,
    )
    soft = await skipped.create_tool_approval_card(
        thread_id="t2",
        task_id="task-2",
        server_name="edms",
        tool_name="write_doc",
        side_effect="write",
        risk_score=0.9,
        argument_preview="x=1",
        owner_user_id=ACTOR,
    )
    none_needed = await skipped.issue_step_up_challenge(soft.card_id, actor_subject=ACTOR)
    assert none_needed.required is False
    assert none_needed.method == "none"


@pytest.mark.asyncio
async def test_step_up_required_for_high_risk_mcp() -> None:
    from palatium_ai.domain.hitl.step_up import mint_hmac_step_up_assertion

    service = HitlService(
        InMemoryHitlCardStore(),
        signing_secret=HITL_TEST_HMAC,
        manager_roles=frozenset({"manager"}),
        step_up_required=True,
    )
    card = await service.create_tool_approval_card(
        thread_id="t1",
        task_id="task-1",
        server_name="edms",
        tool_name="write_doc",
        side_effect="write",
        risk_score=0.9,
        argument_preview="x=1",
        owner_user_id=ACTOR,
    )
    body = _resolve(card, action_id="approve", idem="idem-step-missing")
    with pytest.raises(HitlInvalidActionError, match="step_up"):
        await service.resolve(card.card_id, body, actor_subject=ACTOR)

    ok = HITLResolveRequest(
        action_id="approve",
        action_token=body.action_token,
        idempotency_key="idem-step-ok-01",
        step_up_assertion=mint_hmac_step_up_assertion(
            secret=HITL_TEST_HMAC,
            card_id=card.card_id,
            subject=ACTOR,
        ),
    )
    result = await service.resolve(card.card_id, ok, actor_subject=ACTOR)
    assert result.card.status == "resolved"


@pytest.mark.asyncio
async def test_escalate_notifies_oob_once() -> None:
    notices: list[object] = []

    class _Capture:
        async def notify_escalation(self, notice: object) -> None:
            notices.append(notice)

    store = InMemoryHitlCardStore()
    service = HitlService(
        store,
        signing_secret=HITL_TEST_HMAC,
        manager_roles=frozenset({"manager"}),
        notifier=_Capture(),  # type: ignore[arg-type]
    )
    card = await service.create_tool_approval_card(
        thread_id="t1",
        task_id="task-1",
        server_name="edms",
        tool_name="write_doc",
        side_effect="write",
        risk_score=0.9,
        argument_preview="x=1",
        owner_user_id=ACTOR,
        org_id="org-1",
    )
    expired = card.model_copy(update={"expires_at": datetime.now(UTC) - timedelta(seconds=1)})
    await store.save(expired)
    closed = await service._expire_card(expired, now=datetime.now(UTC))
    assert closed.status == "escalated"
    assert len(notices) == 1
    # CAS lose must not re-notify
    await service._expire_card(expired, now=datetime.now(UTC))
    assert len(notices) == 1


@pytest.mark.asyncio
async def test_chaos_concurrent_respond_and_sweep() -> None:
    """Owner resolve and sweep race: exactly one terminal writer wins."""
    import asyncio

    store = InMemoryHitlCardStore()
    service = _service(store)
    card = await service.create_review_card(
        thread_id="t1",
        task_id="task-1",
        document=_document(),
        confidence=0.2,
        owner_user_id=ACTOR,
    )
    expired = card.model_copy(update={"expires_at": datetime.now(UTC) - timedelta(seconds=1)})
    # Keep tokens valid for resolve path, but mark expired for sweep branch.
    await store.save(card)

    async def _user() -> str:
        try:
            await service.resolve(
                card.card_id,
                _resolve(card, idem="idem-chaos-user"),
                actor_subject=ACTOR,
            )
            return "resolved"
        except Exception as exc:  # noqa: BLE001
            return type(exc).__name__

    async def _sweep() -> str:
        await store.save(expired)
        closed = await service._expire_card(expired, now=datetime.now(UTC))
        return closed.status

    outcomes = await asyncio.gather(_user(), _sweep())
    stored = await store.get(card.card_id)
    assert stored is not None
    assert stored.status in {"resolved", "escalated"}
    assert "resolved" in outcomes or "escalated" in outcomes


def test_mcp_write_floor_applied() -> None:
    assert HitlRiskPolicy.for_mcp_tool(0.1) == pytest.approx(HitlRiskPolicy.MCP_WRITE_FLOOR)


def test_clamp_ttl() -> None:
    assert clamp_ttl_seconds(60) == 5 * 60
    assert clamp_ttl_seconds(40 * 60) == 30 * 60
    assert clamp_ttl_seconds(None) == 15 * 60

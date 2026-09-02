# src/palatium_ai/application/services/hitl_service.py

"""HITL use-cases: создание и резолв кликабельных карточек."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from hashlib import sha256
from typing import TYPE_CHECKING

from palatium_ai.core.exceptions import PalatiumError
from palatium_ai.core.observability.audit import get_audit_logger
from palatium_ai.core.observability.metrics import agent_metrics
from palatium_ai.domain.content import ContentDocument
from palatium_ai.domain.hitl.action_tokens import (
    MANAGER_TOKEN_SUBJECT,
    mint_action_token,
    new_token_nonce,
    verify_action_token,
)
from palatium_ai.domain.hitl.cards import (
    HITLCardView,
    HITLOption,
    HITLResolveRequest,
    HITLResolveResult,
    clamp_ttl_seconds,
    default_review_options,
    default_tool_approval_options,
    new_card_id,
)
from palatium_ai.domain.hitl.escalation_policy import HitlDeadLetterPolicy, HitlTimeoutPolicy
from palatium_ai.domain.hitl.notify import HitlEscalationNotice, HitlNotifyPolicy
from palatium_ai.domain.hitl.risk_policy import HitlRiskPolicy
from palatium_ai.domain.hitl.step_up import (
    HitlStepUpChallenge,
    HitlStepUpPolicy,
    HmacHitlStepUpVerifier,
)

if TYPE_CHECKING:
    from palatium_ai.domain.content import ActionSpec
    from palatium_ai.domain.hitl.notify import HitlNotifierPort
    from palatium_ai.domain.hitl.ports import HitlCardStore, HitlDenyResumePort
    from palatium_ai.domain.hitl.step_up import HitlStepUpProviderPort


def document_content_sha256(document: ContentDocument) -> str:
    """Canonical digest of the document under quality review."""
    payload = document.model_dump_json(exclude_none=True)
    return sha256(payload.encode("utf-8")).hexdigest()


class HitlCardNotFoundError(PalatiumError):
    """Карточка не найдена."""


class HitlCardConflictError(PalatiumError):
    """Карточка уже обработана другим ответом."""


class HitlCardGoneError(PalatiumError):
    """Карточка просрочена / закрыта."""


class HitlInvalidActionError(PalatiumError):
    """action_id не входит в options карточки или action_token невалиден."""


class HitlService:
    """Серверная истина для HITL: TTL, идемпотентность, эскалация."""

    def __init__(
        self,
        store: HitlCardStore,
        *,
        signing_secret: str,
        manager_roles: frozenset[str] | tuple[str, ...] | None = None,
        step_up_required: bool = False,
        step_up_provider: HitlStepUpProviderPort | None = None,
        step_up_verifier: HitlStepUpProviderPort | None = None,
        notifier: HitlNotifierPort | None = None,
        deny_resume: HitlDenyResumePort | None = None,
    ) -> None:
        secret = signing_secret.strip()
        if len(secret) < 16:
            raise ValueError("HITL signing_secret must be at least 16 characters")
        self._store = store
        self._signing_secret = secret
        roles = manager_roles if manager_roles is not None else frozenset({"manager", "admin"})
        self._manager_roles = frozenset(role.strip() for role in roles if role.strip())
        self._step_up_required = step_up_required
        provider = step_up_provider or step_up_verifier or HmacHitlStepUpVerifier(secret)
        self._step_up_provider = provider
        self._step_up_verifier = provider
        self._notifier = notifier
        self._deny_resume = deny_resume

    def bind_deny_resume(self, deny_resume: HitlDenyResumePort) -> None:
        """Late-bind graph deny port after IntentService is constructed (no circular ctor)."""
        self._deny_resume = deny_resume

    async def create_choice_card(
        self,
        *,
        thread_id: str,
        task_id: str,
        title: str,
        body: str | None,
        actions: tuple[ActionSpec, ...] | list[ActionSpec],
        risk_score: float | None = None,
        owner_user_id: str | None = None,
        org_id: str | None = None,
        ttl_seconds: int | None = None,
    ) -> HITLCardView:
        """Mint a clickable multi-option card (user picks one alternative)."""
        options_src = tuple(actions)
        if len(options_src) < 1:
            raise ValueError("create_choice_card requires at least one action")
        now = datetime.now(UTC)
        ttl = clamp_ttl_seconds(ttl_seconds)
        card_id = new_card_id()
        expires_at = now + timedelta(seconds=ttl)
        nonce = new_token_nonce()
        owner = (owner_user_id or "").strip() or None
        tenant = (org_id or "").strip() or None
        scored = HitlRiskPolicy.for_choice(options_src) if risk_score is None else max(0.0, min(1.0, risk_score))
        hitl_options = tuple(
            HITLOption(
                action_id=action.action_id,
                label=action.label,
                kind=action.kind,
                style=action.style,
                icon=action.icon,
            )
            for action in options_src
        )
        subject = HitlRiskPolicy.binding_subject(owner_user_id=owner, escalated=False)
        card = HITLCardView(
            card_id=card_id,
            thread_id=thread_id,
            task_id=task_id,
            purpose="user_choice",
            title=(title or "Choose an option")[:300],
            body=body,
            options=self._stamp_options(
                hitl_options,
                card_id=card_id,
                expires_at=expires_at,
                subject=subject,
                nonce=nonce,
            ),
            risk_score=scored,
            status="pending",
            created_at=now,
            expires_at=expires_at,
            owner_user_id=owner,
            org_id=tenant,
            token_nonce=nonce,
        )
        await self._store.save(card)
        await _audit(
            conversation_id=thread_id,
            event="hitl_choice_card_created",
            payload={
                "card_id": card.card_id,
                "task_id": task_id,
                "options": str(len(card.options)),
                "expires_at": card.expires_at.isoformat(),
                "risk_score": str(card.risk_score),
            },
        )
        agent_metrics.record_human_escalation("hitl_choice_card_created")
        return card

    async def create_review_card(
        self,
        *,
        thread_id: str,
        task_id: str,
        document: ContentDocument,
        confidence: float,
        owner_user_id: str | None = None,
        org_id: str | None = None,
        ttl_seconds: int | None = None,
    ) -> HITLCardView:
        """Создаёт карточку Approve/Reject при requires_review."""
        now = datetime.now(UTC)
        ttl = clamp_ttl_seconds(ttl_seconds)
        risk_score = HitlRiskPolicy.for_quality(confidence)
        card_id = new_card_id()
        expires_at = now + timedelta(seconds=ttl)
        nonce = new_token_nonce()
        owner = (owner_user_id or "").strip() or None
        tenant = (org_id or "").strip() or None
        subject = HitlRiskPolicy.binding_subject(owner_user_id=owner, escalated=False)
        content_digest = document_content_sha256(document)

        card = HITLCardView(
            card_id=card_id,
            thread_id=thread_id,
            task_id=task_id,
            title=document.title or "Review required",
            body=(
                "Quality gate flagged this answer. Approve to keep it, or Reject & revise "
                "to regenerate — do not reply with a numbered menu."
            ),
            options=self._stamp_options(
                default_review_options(),
                card_id=card_id,
                expires_at=expires_at,
                subject=subject,
                nonce=nonce,
            ),
            risk_score=risk_score,
            status="pending",
            created_at=now,
            expires_at=expires_at,
            owner_user_id=owner,
            org_id=tenant,
            token_nonce=nonce,
            content_sha256=content_digest,
        )
        await self._store.save(card)
        await _audit(
            conversation_id=thread_id,
            event="hitl_card_created",
            payload={
                "card_id": card.card_id,
                "task_id": task_id,
                "risk_score": str(card.risk_score),
                "expires_at": card.expires_at.isoformat(),
            },
        )
        agent_metrics.record_human_escalation("hitl_card_created")
        return card

    async def create_tool_approval_card(
        self,
        *,
        thread_id: str,
        task_id: str,
        server_name: str,
        tool_name: str,
        side_effect: str,
        risk_score: float,
        argument_preview: str,
        owner_user_id: str | None = None,
        org_id: str | None = None,
        ttl_seconds: int | None = None,
    ) -> HITLCardView:
        """Create HITL card that must be resolved before a mutating MCP call resumes."""
        now = datetime.now(UTC)
        ttl = clamp_ttl_seconds(ttl_seconds)
        clamped_risk = HitlRiskPolicy.for_mcp_tool(risk_score)
        preview = argument_preview.strip()[:500] or "(no arguments)"
        card_id = new_card_id()
        expires_at = now + timedelta(seconds=ttl)
        nonce = new_token_nonce()
        owner = (owner_user_id or "").strip() or None
        tenant = (org_id or "").strip() or None
        # Manager queue is org-scoped; write/high-risk without org cannot be operated.
        if (
            side_effect.strip().lower() == "write" or clamped_risk > HitlTimeoutPolicy.RISK_ESCALATION_THRESHOLD
        ) and not tenant:
            raise HitlInvalidActionError(
                "org_id required for write/high-risk MCP tool approval cards",
            )
        subject = HitlRiskPolicy.binding_subject(owner_user_id=owner, escalated=False)
        card = HITLCardView(
            card_id=card_id,
            thread_id=thread_id,
            task_id=task_id,
            purpose="mcp_tool_approval",
            title=f"Approve MCP tool: {server_name}.{tool_name}",
            body=(f"Side effect={side_effect}. Tool will not run until you approve. Arguments: {preview}"),
            options=self._stamp_options(
                default_tool_approval_options(),
                card_id=card_id,
                expires_at=expires_at,
                subject=subject,
                nonce=nonce,
            ),
            risk_score=clamped_risk,
            status="pending",
            created_at=now,
            expires_at=expires_at,
            owner_user_id=owner,
            org_id=tenant,
            token_nonce=nonce,
        )
        await self._store.save(card)
        await _audit(
            conversation_id=thread_id,
            event="hitl_tool_approval_created",
            payload={
                "card_id": card.card_id,
                "task_id": task_id,
                "server_name": server_name,
                "tool_name": tool_name,
                "side_effect": side_effect,
                "risk_score": str(card.risk_score),
            },
        )
        agent_metrics.record_human_escalation("hitl_tool_approval_created")
        return card

    async def get_card(self, card_id: str) -> HITLCardView | None:
        """Read card; apply pending→escalate/auto-reject or escalated→dead_letter if TTL passed."""
        card = await self._store.get(card_id)
        if card is None:
            return None
        return await self._apply_ttl_if_due(card)

    async def _apply_ttl_if_due(self, card: HITLCardView) -> HITLCardView:
        """Lazy TTL close so GET/queue stay consistent without waiting for sweep."""
        now = datetime.now(UTC)
        if card.expires_at > now:
            return card
        if card.status == "pending":
            return await self._expire_card(card, now=now)
        if card.status == "escalated":
            return await self._dead_letter_escalated(card, now=now)
        return card

    def step_up_enforced_for(self, card: HITLCardView) -> bool:
        """Return True when this deployment requires step-up for the card."""
        return self._step_up_required and HitlStepUpPolicy.required_for(card)

    async def issue_step_up_challenge(
        self,
        card_id: str,
        *,
        actor_subject: str,
    ) -> HitlStepUpChallenge:
        """Issue a step-up ceremony for the card owner (HMAC stub until WebAuthn)."""
        card = await self._store.get(card_id)
        if card is None:
            raise HitlCardNotFoundError(f"HITL card not found: {card_id}")
        if card.status != "pending":
            agent_metrics.record_hitl_deny("conflict")
            raise HitlCardConflictError(f"HITL card already {card.status}: {card_id}")
        now = datetime.now(UTC)
        if card.expires_at <= now:
            closed = await self._expire_card(card, now=now)
            agent_metrics.record_hitl_deny("expired")
            raise HitlCardGoneError(f"HITL card expired ({closed.status}): {card_id}")

        owner = (card.owner_user_id or "").strip()
        actor = actor_subject.strip()
        if owner and actor != owner:
            agent_metrics.record_hitl_deny("subject_mismatch")
            raise HitlInvalidActionError(f"step-up subject mismatch for card {card.card_id}")

        if not self.step_up_enforced_for(card):
            return HitlStepUpChallenge(
                required=False,
                method="none",
                assertion=None,
                card_id=card.card_id,
            )

        challenge = self._step_up_provider.issue_challenge(
            card_id=card.card_id,
            subject=actor,
        )
        await _audit(
            conversation_id=card.thread_id,
            event="hitl_step_up_challenge_issued",
            payload={
                "card_id": card.card_id,
                "method": challenge.method,
                "actor_subject": actor[:128],
                "risk_score": str(card.risk_score),
            },
        )
        return challenge

    async def resolve(
        self,
        card_id: str,
        request: HITLResolveRequest,
        *,
        actor_subject: str,
    ) -> HITLResolveResult:
        """Принимает клик по карточке с проверкой TTL и idempotency key."""
        card = await self._store.get(card_id)
        if card is None:
            raise HitlCardNotFoundError(f"HITL card not found: {card_id}")

        existing_key = await self._store.get_idempotency_key(card_id)
        if card.status == "resolved" and existing_key == request.idempotency_key:
            return HITLResolveResult(
                card=card.without_secrets(),
                replayed=True,
                message="Idempotent replay",
            )

        if card.status in {"resolved", "escalated", "auto_rejected", "dead_letter"}:
            agent_metrics.record_hitl_deny("conflict")
            raise HitlCardConflictError(f"HITL card already {card.status}: {card_id}")

        now = datetime.now(UTC)
        if card.expires_at <= now or card.status == "expired":
            closed = await self._expire_card(card, now=now)
            agent_metrics.record_hitl_deny("expired")
            raise HitlCardGoneError(f"HITL card expired ({closed.status}): {card_id}")

        return await self._finalize_resolve(
            card,
            request,
            expected_status="pending",
            now=now,
            token_subject=HitlRiskPolicy.binding_subject(
                owner_user_id=card.owner_user_id,
                escalated=False,
            ),
            actor_subject=actor_subject,
            require_step_up=self._step_up_required and HitlStepUpPolicy.required_for(card),
        )

    async def resolve_escalated(
        self,
        card_id: str,
        request: HITLResolveRequest,
        *,
        actor_subject: str,
    ) -> HITLResolveResult:
        """Resolve a high-risk card stuck in escalated status (manager step-up)."""
        card = await self._store.get(card_id)
        if card is None:
            raise HitlCardNotFoundError(f"HITL card not found: {card_id}")

        existing_key = await self._store.get_idempotency_key(card_id)
        if card.status == "resolved" and existing_key == request.idempotency_key:
            return HITLResolveResult(
                card=card.without_secrets(),
                replayed=True,
                message="Idempotent replay",
            )

        if card.status != "escalated":
            agent_metrics.record_hitl_deny("conflict")
            raise HitlCardConflictError(f"HITL card not escalated (status={card.status}): {card_id}")

        now = datetime.now(UTC)
        if card.expires_at <= now:
            closed = await self._dead_letter_escalated(card, now=now)
            agent_metrics.record_hitl_deny("dead_letter")
            raise HitlCardGoneError(f"HITL card dead-lettered ({closed.status}): {card_id}")

        return await self._finalize_resolve(
            card,
            request,
            expected_status="escalated",
            now=now,
            token_subject=MANAGER_TOKEN_SUBJECT,
            actor_subject=actor_subject,
            audit_event="hitl_card_manager_resolved",
            require_manager_subject=True,
        )

    async def _finalize_resolve(
        self,
        card: HITLCardView,
        request: HITLResolveRequest,
        *,
        expected_status: str,
        now: datetime,
        token_subject: str,
        actor_subject: str,
        audit_event: str = "hitl_card_resolved",
        require_manager_subject: bool = False,
        require_step_up: bool = False,
    ) -> HITLResolveResult:
        allowed = {option.action_id for option in card.options}
        if request.action_id not in allowed:
            agent_metrics.record_hitl_deny("invalid_action")
            raise HitlInvalidActionError(f"action_id '{request.action_id}' is not allowed for card {card.card_id}")

        if require_manager_subject:
            # Token is bound to role:manager; actor must be a real principal (checked by router).
            bound_subject = MANAGER_TOKEN_SUBJECT
        else:
            bound_subject = token_subject
            owner = (card.owner_user_id or "").strip()
            actor = actor_subject.strip()
            if owner and actor != owner:
                agent_metrics.record_hitl_deny("subject_mismatch")
                raise HitlInvalidActionError(f"action_token subject mismatch for card {card.card_id}")

        if require_step_up:
            assertion = (request.step_up_assertion or "").strip()
            if not assertion or not self._step_up_verifier.verify(
                card_id=card.card_id,
                subject=actor_subject.strip(),
                assertion=assertion,
            ):
                agent_metrics.record_hitl_deny("step_up")
                raise HitlInvalidActionError(f"step_up_assertion required for high-risk card {card.card_id}")

        if not card.token_nonce or not verify_action_token(
            secret=self._signing_secret,
            token=request.action_token,
            card_id=card.card_id,
            action_id=request.action_id,
            expires_at=card.expires_at,
            subject=bound_subject,
            nonce=card.token_nonce,
        ):
            agent_metrics.record_hitl_deny("forge")
            raise HitlInvalidActionError(f"action_token invalid for card {card.card_id} action {request.action_id}")

        # One-time consume: rotate nonce and strip tokens on the stored card.
        resolved = card.model_copy(
            update={
                "status": "resolved",
                "resolved_action_id": request.action_id,
                "resolved_at": now,
                "token_nonce": new_token_nonce(),
                "options": tuple(option.model_copy(update={"action_token": ""}) for option in card.options),
            }
        )
        won = await self._store.compare_and_set(
            resolved,
            expected_status=expected_status,
            idempotency_key=request.idempotency_key,
        )
        if not won:
            latest = await self._store.get(card.card_id)
            existing_key = await self._store.get_idempotency_key(card.card_id)
            if latest is not None and latest.status == "resolved" and existing_key == request.idempotency_key:
                return HITLResolveResult(
                    card=latest.without_secrets(),
                    replayed=True,
                    message="Idempotent replay",
                )
            status = latest.status if latest is not None else "missing"
            agent_metrics.record_hitl_deny("conflict")
            raise HitlCardConflictError(f"HITL card already {status}: {card.card_id}")
        await _audit(
            conversation_id=card.thread_id,
            event=audit_event,
            payload={
                "card_id": card.card_id,
                "action_id": request.action_id,
                "idempotency_key": request.idempotency_key,
                "risk_score": str(card.risk_score),
                "from_status": expected_status,
                "actor_subject": actor_subject.strip()[:128],
                "content_sha256": (card.content_sha256 or "")[:64],
            },
        )
        return HITLResolveResult(
            card=resolved.without_secrets(),
            replayed=False,
            message="Resolved",
        )

    def _stamp_options(
        self,
        options: tuple[HITLOption, ...],
        *,
        card_id: str,
        expires_at: datetime,
        subject: str,
        nonce: str,
    ) -> tuple[HITLOption, ...]:
        stamped: list[HITLOption] = []
        for option in options:
            token = mint_action_token(
                secret=self._signing_secret,
                card_id=card_id,
                action_id=option.action_id,
                expires_at=expires_at,
                subject=subject,
                nonce=nonce,
            )
            stamped.append(option.model_copy(update={"action_token": token}))
        return tuple(stamped)

    async def _expire_card(self, card: HITLCardView, *, now: datetime) -> HITLCardView:
        """Просрочка pending: high risk → escalate, иначе auto-reject (CAS)."""
        if card.status in {"resolved", "escalated", "auto_rejected", "dead_letter"}:
            return card

        decision = HitlTimeoutPolicy.on_expiry(
            risk_score=card.risk_score,
            manager_roles=self._manager_roles,
        )
        if decision.outcome == "escalate":
            status = "escalated"
            event = "hitl_card_escalated"
            agent_metrics.record_human_escalation("hitl_timeout_escalation")
            manager_ttl = clamp_ttl_seconds(None)
            new_expires = now + timedelta(seconds=manager_ttl)
            nonce = new_token_nonce()
            restamped = self._stamp_options(
                tuple(
                    HITLOption(
                        action_id=option.action_id,
                        label=option.label,
                        kind=option.kind,
                        style=option.style,
                        icon=option.icon,
                    )
                    for option in card.options
                ),
                card_id=card.card_id,
                expires_at=new_expires,
                subject=MANAGER_TOKEN_SUBJECT,
                nonce=nonce,
            )
            closed = card.model_copy(
                update={
                    "status": status,
                    "resolved_at": now,
                    "resolved_action_id": None,
                    "escalate_to_roles": decision.escalate_to_roles,
                    "expires_at": new_expires,
                    "options": restamped,
                    "token_nonce": nonce,
                }
            )
        else:
            status = "auto_rejected"
            event = "hitl_card_auto_rejected"
            closed = card.model_copy(
                update={
                    "status": status,
                    "resolved_at": now,
                    "resolved_action_id": "reject",
                    "escalate_to_roles": decision.escalate_to_roles,
                    "token_nonce": new_token_nonce(),
                    "options": tuple(option.model_copy(update={"action_token": ""}) for option in card.options),
                }
            )
        won = await self._store.compare_and_set(closed, expected_status="pending")
        if not won:
            latest = await self._store.get(card.card_id)
            if latest is not None:
                return latest
            return closed
        await _audit(
            conversation_id=card.thread_id,
            event=event,
            payload={
                "card_id": card.card_id,
                "risk_score": str(card.risk_score),
                "status": status,
                "reason": decision.reason,
                "escalate_to_roles": ",".join(decision.escalate_to_roles),
            },
        )
        if (
            status == "escalated"
            and self._notifier is not None
            and HitlNotifyPolicy.should_notify_on_escalate(
                risk_score=card.risk_score,
                purpose=card.purpose,
            )
        ):
            try:
                await self._notifier.notify_escalation(
                    HitlEscalationNotice(
                        card_id=card.card_id,
                        thread_id=card.thread_id,
                        task_id=card.task_id,
                        purpose=card.purpose,
                        org_id=card.org_id,
                        risk_score=card.risk_score,
                        escalate_to_roles=decision.escalate_to_roles,
                        reason=decision.reason,
                    )
                )
            except Exception:  # noqa: BLE001 — OOB must not break sweep CAS path
                agent_metrics.record_hitl_deny("notify_failed")
        if status == "auto_rejected":
            await self._maybe_deny_resume_interrupt(closed, reason=decision.reason)
        return closed

    async def _dead_letter_escalated(self, card: HITLCardView, *, now: datetime) -> HITLCardView:
        """Close escalated card after manager TTL without resolve (no re-escalate)."""
        if card.status != "escalated":
            return card
        decision = HitlDeadLetterPolicy.on_manager_ttl_expiry()
        closed = card.model_copy(
            update={
                "status": "dead_letter",
                "resolved_at": now,
                "resolved_action_id": "reject",
                "token_nonce": new_token_nonce(),
                "options": tuple(option.model_copy(update={"action_token": ""}) for option in card.options),
            }
        )
        won = await self._store.compare_and_set(closed, expected_status="escalated")
        if not won:
            latest = await self._store.get(card.card_id)
            if latest is not None:
                return latest
            return closed
        agent_metrics.record_human_escalation("hitl_dead_letter")
        await _audit(
            conversation_id=card.thread_id,
            event="hitl_card_dead_letter",
            payload={
                "card_id": card.card_id,
                "risk_score": str(card.risk_score),
                "status": "dead_letter",
                "reason": decision.reason,
                "escalate_to_roles": ",".join(card.escalate_to_roles),
            },
        )
        if self._notifier is not None:
            try:
                await self._notifier.notify_escalation(
                    HitlEscalationNotice(
                        card_id=card.card_id,
                        thread_id=card.thread_id,
                        task_id=card.task_id,
                        purpose=card.purpose,
                        org_id=card.org_id,
                        risk_score=card.risk_score,
                        escalate_to_roles=card.escalate_to_roles,
                        reason=decision.reason,
                    )
                )
            except Exception:  # noqa: BLE001 — OOB must not break sweep CAS path
                agent_metrics.record_hitl_deny("notify_failed")
        await self._maybe_deny_resume_interrupt(closed, reason=decision.reason)
        return closed

    async def _maybe_deny_resume_interrupt(self, card: HITLCardView, *, reason: str) -> None:
        """Fail-closed: terminal deny must also clear an open mcp_tool_approval interrupt."""
        if card.purpose != "mcp_tool_approval":
            return
        if self._deny_resume is None:
            agent_metrics.record_hitl_deny("deny_resume_unbound")
            return
        try:
            await self._deny_resume.deny_tool_interrupt(
                thread_id=card.thread_id,
                task_id=card.task_id,
                card_id=card.card_id,
                reason=reason,
            )
        except Exception:  # noqa: BLE001 — sweep/TTL must not crash on resume failure
            agent_metrics.record_hitl_deny("deny_resume_failed")

    async def list_escalated(
        self,
        *,
        org_id: str | None = None,
        include_secrets: bool = False,
    ) -> list[HITLCardView]:
        """List escalated cards; tenant-scoped; tokens redacted by default.

        Expired escalated rows are closed to ``dead_letter`` before listing.
        """
        tenant = (org_id or "").strip()
        items: list[HITLCardView] = []
        for card in await self._store.list_cards():
            if card.status not in {"escalated", "pending"}:
                continue
            refreshed = await self._apply_ttl_if_due(card)
            if refreshed.status != "escalated":
                continue
            if tenant and (refreshed.org_id or "") != tenant:
                continue
            items.append(refreshed if include_secrets else refreshed.without_secrets())
        return items

    async def sweep_expired(self) -> dict[str, int]:
        """Close expired pending (escalate/auto-reject) and escalated (dead_letter)."""
        now = datetime.now(UTC)
        escalated = 0
        auto_rejected = 0
        dead_letter = 0
        for card in await self._store.list_cards():
            if card.expires_at > now:
                continue
            if card.status == "pending":
                closed = await self._expire_card(card, now=now)
                if closed.status == "escalated":
                    escalated += 1
                elif closed.status == "auto_rejected":
                    auto_rejected += 1
            elif card.status == "escalated":
                closed = await self._dead_letter_escalated(card, now=now)
                if closed.status == "dead_letter":
                    dead_letter += 1
        return {
            "escalated": escalated,
            "auto_rejected": auto_rejected,
            "dead_letter": dead_letter,
        }


async def _audit(*, conversation_id: str, event: str, payload: dict[str, str]) -> None:
    await get_audit_logger().append_async(
        timestamp=datetime.now(UTC).isoformat(),
        conversation_id=conversation_id,
        event=event,
        metadata=payload,
    )

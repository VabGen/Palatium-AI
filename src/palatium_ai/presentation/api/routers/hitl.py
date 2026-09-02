# src/palatium_ai/presentation/api/routers/hitl.py

"""API для HITL-карточек."""

from __future__ import annotations

from typing import TYPE_CHECKING

from fastapi import APIRouter, HTTPException, Request, status
from pydantic import BaseModel, Field

from palatium_ai.application.services.hitl_service import (
    HitlCardConflictError,
    HitlCardGoneError,
    HitlCardNotFoundError,
    HitlInvalidActionError,
)
from palatium_ai.application.services.kill_switch import KillSwitchEngagedError
from palatium_ai.core.observability.metrics import agent_metrics
from palatium_ai.domain.agents.formatter import FormatterTaskResult
from palatium_ai.domain.hitl.cards import HITLCardView, HITLResolveRequest, HITLResolveResult
from palatium_ai.domain.hitl.step_up import HitlStepUpChallenge
from palatium_ai.domain.sessions.errors import SessionOwnershipError
from palatium_ai.presentation.resources import get_app_resources
from palatium_ai.presentation.security.deps import get_principal, principal_is_admin, require_manager
from palatium_ai.presentation.security.ownership import load_session_for_principal

if TYPE_CHECKING:
    from palatium_ai.application.bootstrap import AppResources
    from palatium_ai.presentation.security.principal import AuthPrincipal

router = APIRouter()


class HitlRespondResponse(BaseModel):
    """HITL resolve result plus optional resumed formatter output for tool approvals."""

    resolve: HITLResolveResult
    resumed: FormatterTaskResult | None = None


class EscalatedHitlQueue(BaseModel):
    """Manager queue of high-risk timeout escalations."""

    items: list[HITLCardView]


def _principal_is_manager(request: Request, principal: AuthPrincipal) -> bool:
    security = request.app.state.security_config
    return principal.has_any_role(security.manager_role_set)


def _same_org(card: HITLCardView, principal: AuthPrincipal) -> bool:
    """Fail-closed tenant match: both card and principal must carry the same org_id."""
    card_org = (card.org_id or "").strip()
    principal_org = (principal.org_id or "").strip()
    if not card_org or not principal_org:
        return False
    return card_org == principal_org


def _require_manager_org(principal: AuthPrincipal) -> str:
    org = (principal.org_id or "").strip()
    if not org:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="org_id claim required for manager HITL actions",
        )
    return org


@router.get("/queue/escalated", response_model=EscalatedHitlQueue)
async def list_escalated_hitl_cards(request: Request) -> EscalatedHitlQueue:
    """List HITL cards escalated after high-risk timeout (manager role required)."""
    principal = require_manager(request)
    org = _require_manager_org(principal)
    resources = get_app_resources(request.app)
    items = await resources.hitl_service.list_escalated(
        org_id=org,
        include_secrets=False,
    )
    return EscalatedHitlQueue(items=items)


class DevMintToolApprovalRequest(BaseModel):
    """Development-only mint of mcp_tool_approval (deterministic write-HITL smoke)."""

    thread_id: str = Field(min_length=1, max_length=128)
    server_name: str = Field(default="edms", min_length=1, max_length=64)
    tool_name: str = Field(default="archive_document", min_length=1, max_length=128)
    side_effect: str = Field(default="write", min_length=1, max_length=32)
    risk_score: float = Field(default=0.85, ge=0.0, le=1.0)
    argument_preview: str = Field(default="document_id=DOC-SMOKE", max_length=500)


@router.post("/dev/mint-tool-approval", response_model=HITLCardView)
async def mint_dev_tool_approval(
    body: DevMintToolApprovalRequest,
    request: Request,
) -> HITLCardView:
    """Mint a write MCP HITL card without LLM routing (development only)."""
    settings = request.app.state.settings
    if settings.app.environment != "development":
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Dev HITL mint is only available in development",
        )
    principal = get_principal(request)
    resources = get_app_resources(request.app)
    await load_session_for_principal(
        request=request,
        principal=principal,
        session_service=resources.session_service,
        thread_id=body.thread_id,
        allow_missing=False,
    )
    return await resources.hitl_service.create_tool_approval_card(
        thread_id=body.thread_id,
        task_id=f"dev-mint-{body.tool_name}",
        server_name=body.server_name,
        tool_name=body.tool_name,
        side_effect=body.side_effect,
        risk_score=body.risk_score,
        argument_preview=body.argument_preview,
        owner_user_id=principal.subject,
        org_id=principal.org_id,
    )


@router.get("/{card_id}", response_model=HITLCardView)
async def get_hitl_card(card_id: str, request: Request) -> HITLCardView:
    """Owner thread GET, or manager GET for same-org escalated cards (tokens for click)."""
    principal = get_principal(request)
    resources = get_app_resources(request.app)
    card = await resources.hitl_service.get_card(card_id)
    if card is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="HITL card not found")

    if card.status == "escalated" and _principal_is_manager(request, principal):
        if not _same_org(card, principal):
            agent_metrics.record_hitl_deny("forbidden")
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Escalated card belongs to another org",
            )
        return card

    try:
        await load_session_for_principal(
            request=request,
            principal=principal,
            session_service=resources.session_service,
            thread_id=card.thread_id,
            allow_missing=False,
        )
    except HTTPException as exc:
        if exc.status_code == status.HTTP_403_FORBIDDEN:
            agent_metrics.record_hitl_deny("forbidden")
        raise
    return card


async def _resolve_hitl(
    resources: AppResources,
    card_id: str,
    body: HITLResolveRequest,
    *,
    actor_subject: str,
    escalated: bool = False,
) -> HITLResolveResult:
    try:
        if escalated:
            return await resources.hitl_service.resolve_escalated(
                card_id,
                body,
                actor_subject=actor_subject,
            )
        return await resources.hitl_service.resolve(
            card_id,
            body,
            actor_subject=actor_subject,
        )
    except HitlCardNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    except HitlCardConflictError as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from exc
    except HitlCardGoneError as exc:
        raise HTTPException(status_code=status.HTTP_410_GONE, detail=str(exc)) from exc
    except HitlInvalidActionError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc


def _determine_resume_identity(
    card: HITLCardView,
    principal: AuthPrincipal,
    acting_manager: bool,
) -> tuple[str, str]:
    """Calculate user_id and org_id for resuming based on manager flag.

    If ``acting_manager`` is true, the resume must run as the card owner.
    Otherwise it runs as the current principal.
    """
    if acting_manager:
        owner = (card.owner_user_id or "").strip()
        if not owner:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Escalated card missing owner_user_id; cannot resume thread",
            )
        resume_user_id = owner
        resume_org_id = (card.org_id or "").strip() or principal.org_id
    else:
        resume_user_id = principal.subject
        resume_org_id = principal.org_id
    return resume_user_id, resume_org_id


async def _resume_after_hitl(
    *,
    resources: AppResources,
    card: HITLCardView,
    body: HITLResolveRequest,
    principal: AuthPrincipal,
    resolve: HITLResolveResult,
    is_admin: bool,
    acting_manager: bool = False,
) -> FormatterTaskResult | None:
    """Resume graph after HITL resolve.

    Manager resolve already passed org/role gates; resume must run as the
    *thread owner* so SessionOwnership does not deny the actuation (split-brain).

    On mcp_tool_approval resume failure after a committed resolve, compensate with
    system deny so the tool interrupt cannot hang with an already-consumed card.
    """
    if resolve.replayed:
        return None
    resume_user_id, resume_org_id = _determine_resume_identity(card, principal, acting_manager)
    try:
        return await _perform_resume(
            resources,
            card,
            body,
            resume_user_id,
            resume_org_id,
            is_admin,
        )
    except Exception as exc:
        if card.purpose == "mcp_tool_approval":
            await _compensate_tool_resume_failure(resources=resources, card=card, cause=exc)
        if isinstance(exc, KillSwitchEngagedError):
            raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail=str(exc)) from exc
        if isinstance(exc, SessionOwnershipError):
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=str(exc)) from exc
        if isinstance(exc, ValueError):
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
        if isinstance(exc, HTTPException):
            raise
        raise


async def _perform_resume(
    resources: AppResources,
    card: HITLCardView,
    body: HITLResolveRequest,
    resume_user_id: str,
    resume_org_id: str,
    is_admin: bool,
) -> FormatterTaskResult | None:
    """Dispatch resume based on card purpose.

    Returns the formatter result or ``None`` when there is nothing to resume.
    """
    if card.purpose == "mcp_tool_approval":
        return await resources.intent_service.resume_after_tool_approval(
            thread_id=card.thread_id,
            task_id=card.task_id,
            action_id=body.action_id,
            user_id=resume_user_id,
            org_id=resume_org_id,
            is_admin=is_admin,
        )
    if card.purpose == "user_choice":
        return await resources.intent_service.process_hitl_choice(
            thread_id=card.thread_id,
            action_id=body.action_id,
            card=card,
            user_id=resume_user_id,
            org_id=resume_org_id,
            is_admin=is_admin,
        )
    if card.purpose == "quality_review":
        if body.action_id == "reject":
            return await resources.intent_service.revise_after_quality_reject(
                thread_id=card.thread_id,
                task_id=card.task_id,
                user_id=resume_user_id,
                org_id=resume_org_id,
                is_admin=is_admin,
            )
        if body.action_id == "approve":
            await resources.intent_service.acknowledge_quality_approve(
                thread_id=card.thread_id,
                user_id=resume_user_id,
                is_admin=is_admin,
                content_sha256=card.content_sha256,
            )
            return None
    return None


async def _compensate_tool_resume_failure(
    *,
    resources: AppResources,
    card: HITLCardView,
    cause: BaseException,
) -> None:
    """Card already resolved — force reject resume so the tool cannot hang open."""
    try:
        await resources.intent_service.deny_tool_interrupt(
            thread_id=card.thread_id,
            task_id=card.task_id,
            card_id=card.card_id,
            reason=f"resume_failed:{type(cause).__name__}",
        )
        agent_metrics.record_hitl_deny("resume_compensated_deny")
    except Exception:  # noqa: BLE001 — surface the original resume error to the client
        agent_metrics.record_hitl_deny("resume_compensate_failed")


@router.post("/{card_id}/step-up-challenge", response_model=HitlStepUpChallenge)
async def issue_hitl_step_up_challenge(card_id: str, request: Request) -> HitlStepUpChallenge:
    """Owner step-up ceremony before high-risk mcp_tool_approval respond."""
    principal = get_principal(request)
    resources = get_app_resources(request.app)
    card = await resources.hitl_service.get_card(card_id)
    if card is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="HITL card not found")
    try:
        await load_session_for_principal(
            request=request,
            principal=principal,
            session_service=resources.session_service,
            thread_id=card.thread_id,
            allow_missing=False,
        )
    except HTTPException as exc:
        if exc.status_code == status.HTTP_403_FORBIDDEN:
            agent_metrics.record_hitl_deny("forbidden")
        raise
    try:
        return await resources.hitl_service.issue_step_up_challenge(
            card_id,
            actor_subject=principal.subject,
        )
    except HitlCardNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    except HitlCardConflictError as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from exc
    except HitlCardGoneError as exc:
        raise HTTPException(status_code=status.HTTP_410_GONE, detail=str(exc)) from exc
    except HitlInvalidActionError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc


@router.post("/{card_id}/respond", response_model=HitlRespondResponse)
async def respond_hitl_card(
    card_id: str,
    body: HITLResolveRequest,
    request: Request,
) -> HitlRespondResponse:
    """Принимает клик по карточке; mcp_tool_approval resume'ит graph до tool call."""
    principal = get_principal(request)
    resources = get_app_resources(request.app)
    card = await resources.hitl_service.get_card(card_id)
    if card is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="HITL card not found")
    try:
        await load_session_for_principal(
            request=request,
            principal=principal,
            session_service=resources.session_service,
            thread_id=card.thread_id,
            allow_missing=False,
        )
    except HTTPException as exc:
        if exc.status_code == status.HTTP_403_FORBIDDEN:
            agent_metrics.record_hitl_deny("forbidden")
        raise
    resolve = await _resolve_hitl(
        resources,
        card_id,
        body,
        actor_subject=principal.subject,
    )
    resumed = await _resume_after_hitl(
        resources=resources,
        card=card,
        body=body,
        principal=principal,
        resolve=resolve,
        is_admin=principal_is_admin(request, principal),
        acting_manager=False,
    )
    return HitlRespondResponse(resolve=resolve, resumed=resumed)


@router.post("/{card_id}/manager-resolve", response_model=HitlRespondResponse)
async def manager_resolve_hitl_card(
    card_id: str,
    body: HITLResolveRequest,
    request: Request,
) -> HitlRespondResponse:
    """Resolve escalated high-risk HITL cards (manager step-up / TTL queue)."""
    principal = require_manager(request)
    _require_manager_org(principal)
    resources = get_app_resources(request.app)
    card = await resources.hitl_service.get_card(card_id)
    if card is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="HITL card not found")
    if card.status != "escalated":
        agent_metrics.record_hitl_deny("forbidden")
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Only escalated HITL cards can be manager-resolved",
        )
    if not _same_org(card, principal):
        agent_metrics.record_hitl_deny("forbidden")
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Escalated card belongs to another org",
        )
    resolve = await _resolve_hitl(
        resources,
        card_id,
        body,
        actor_subject=principal.subject,
        escalated=True,
    )
    resumed = await _resume_after_hitl(
        resources=resources,
        card=card,
        body=body,
        principal=principal,
        resolve=resolve,
        is_admin=principal_is_admin(request, principal),
        acting_manager=True,
    )
    return HitlRespondResponse(resolve=resolve, resumed=resumed)

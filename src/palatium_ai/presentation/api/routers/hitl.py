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
from palatium_ai.core.exceptions import SessionOwnershipError
from palatium_ai.core.observability.metrics import agent_metrics
from palatium_ai.domain.agents.formatter import FormatterTaskResult
from palatium_ai.domain.hitl.cards import HITLCardView, HITLResolveRequest, HITLResolveResult
from palatium_ai.domain.hitl.step_up import HitlStepUpChallenge
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
    card_org = (card.org_id or "").strip()
    principal_org = (principal.org_id or "").strip()
    if not card_org:
        return True
    return bool(principal_org) and card_org == principal_org


@router.get("/queue/escalated", response_model=EscalatedHitlQueue)
async def list_escalated_hitl_cards(request: Request) -> EscalatedHitlQueue:
    """List HITL cards escalated after high-risk timeout (manager role required)."""
    principal = require_manager(request)
    org = (principal.org_id or "").strip()
    if not org:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="org_id claim required for escalated queue",
        )
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


async def _resume_after_hitl(
    *,
    resources: AppResources,
    card: HITLCardView,
    body: HITLResolveRequest,
    principal: AuthPrincipal,
    resolve: HITLResolveResult,
    is_admin: bool,
) -> FormatterTaskResult | None:
    if resolve.replayed:
        return None
    try:
        if card.purpose == "mcp_tool_approval":
            return await resources.intent_service.resume_after_tool_approval(
                thread_id=card.thread_id,
                task_id=card.task_id,
                action_id=body.action_id,
                user_id=principal.subject,
                org_id=principal.org_id,
                is_admin=is_admin,
            )
        if card.purpose == "user_choice":
            return await resources.intent_service.process_hitl_choice(
                thread_id=card.thread_id,
                action_id=body.action_id,
                card=card,
                user_id=principal.subject,
                org_id=principal.org_id,
                is_admin=is_admin,
            )
        if card.purpose == "quality_review" and body.action_id == "reject":
            return await resources.intent_service.revise_after_quality_reject(
                thread_id=card.thread_id,
                task_id=card.task_id,
                user_id=principal.subject,
                org_id=principal.org_id,
                is_admin=is_admin,
            )
        if card.purpose == "quality_review" and body.action_id == "approve":
            await resources.intent_service.acknowledge_quality_approve(
                thread_id=card.thread_id,
                user_id=principal.subject,
                is_admin=is_admin,
                content_sha256=card.content_sha256,
            )
    except KillSwitchEngagedError as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=str(exc),
        ) from exc
    except SessionOwnershipError as exc:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=str(exc),
        ) from exc
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
    return None


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
    resources = get_app_resources(request.app)
    card = await resources.hitl_service.get_card(card_id)
    if card is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="HITL card not found")
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
    )
    return HitlRespondResponse(resolve=resolve, resumed=resumed)

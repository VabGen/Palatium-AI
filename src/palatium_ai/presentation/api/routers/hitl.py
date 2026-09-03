# src/palatium_ai/presentation/api/routers/hitl.py

"""API для HITL-карточек."""

from __future__ import annotations

from typing import TYPE_CHECKING

from fastapi import APIRouter, HTTPException, Request, status
from pydantic import BaseModel, Field

from palatium_ai.application.services.hitl_respond_facade import (
    HitlCardConflictError,
    HitlCardGoneError,
    HitlCardNotFoundError,
    HitlInvalidActionError,
    HitlRespondOutcome,
    KillSwitchEngagedError,
    SessionOwnershipError,
)
from palatium_ai.core.observability.metrics import agent_metrics
from palatium_ai.domain.agents.formatter import FormatterTaskResult
from palatium_ai.domain.hitl.cards import HITLCardView, HITLResolveRequest, HITLResolveResult
from palatium_ai.domain.hitl.step_up import HitlStepUpChallenge
from palatium_ai.presentation.resources import get_app_resources
from palatium_ai.presentation.security.deps import get_principal, principal_is_admin, require_manager
from palatium_ai.presentation.security.ownership import load_session_for_principal

if TYPE_CHECKING:
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


def _map_hitl_error(exc: Exception) -> HTTPException:
    if isinstance(exc, HitlCardNotFoundError):
        return HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc))
    if isinstance(exc, HitlCardConflictError):
        return HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc))
    if isinstance(exc, HitlCardGoneError):
        return HTTPException(status_code=status.HTTP_410_GONE, detail=str(exc))
    if isinstance(exc, HitlInvalidActionError):
        return HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc))
    if isinstance(exc, KillSwitchEngagedError):
        return HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail=str(exc))
    if isinstance(exc, SessionOwnershipError):
        return HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=str(exc))
    if isinstance(exc, ValueError):
        return HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc))
    raise exc


def _to_response(outcome: HitlRespondOutcome) -> HitlRespondResponse:
    return HitlRespondResponse(resolve=outcome.resolve, resumed=outcome.resumed)


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
    except (HitlCardNotFoundError, HitlCardConflictError, HitlCardGoneError, HitlInvalidActionError) as exc:
        raise _map_hitl_error(exc) from exc


@router.post("/{card_id}/respond", response_model=HitlRespondResponse)
async def respond_hitl_card(
    card_id: str,
    body: HITLResolveRequest,
    request: Request,
) -> HitlRespondResponse:
    """Принимает клик по карточке; mcp_tool_approval resume'ит graph до tool call."""
    principal = get_principal(request)
    resources = get_app_resources(request.app)
    facade = resources.hitl_respond_facade
    if facade is None:
        raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail="HITL facade unavailable")
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
        outcome = await facade.respond(
            card_id,
            body,
            actor_subject=principal.subject,
            actor_org_id=principal.org_id,
            is_admin=principal_is_admin(request, principal),
        )
    except HTTPException as exc:
        if exc.status_code == status.HTTP_403_FORBIDDEN:
            agent_metrics.record_hitl_deny("forbidden")
        raise
    except Exception as exc:
        raise _map_hitl_error(exc) from exc
    return _to_response(outcome)


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
    facade = resources.hitl_respond_facade
    if facade is None:
        raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail="HITL facade unavailable")
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
    try:
        outcome = await facade.respond(
            card_id,
            body,
            actor_subject=principal.subject,
            actor_org_id=principal.org_id,
            is_admin=principal_is_admin(request, principal),
            escalated=True,
            acting_manager=True,
        )
    except Exception as exc:
        raise _map_hitl_error(exc) from exc
    return _to_response(outcome)

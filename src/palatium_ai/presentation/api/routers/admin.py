# src/palatium_ai/presentation/api/routers/admin.py

"""Admin control plane (kill switch)."""

from __future__ import annotations

from fastapi import APIRouter, Request
from pydantic import BaseModel, Field

from palatium_ai.presentation.resources import get_app_resources
from palatium_ai.presentation.security.deps import require_admin

router = APIRouter()


class KillSwitchEngageRequest(BaseModel):
    """Payload for engaging the platform kill switch."""

    reason: str = Field(min_length=3, max_length=500)


class KillSwitchStatusResponse(BaseModel):
    """Current kill-switch state."""

    engaged: bool


@router.get("/kill-switch", response_model=KillSwitchStatusResponse)
async def get_kill_switch(request: Request) -> KillSwitchStatusResponse:
    """Return whether the global kill switch is engaged."""
    require_admin(request)
    resources = get_app_resources(request.app)
    return KillSwitchStatusResponse(engaged=await resources.kill_switch.is_engaged())


@router.post("/kill-switch/engage", response_model=KillSwitchStatusResponse)
async def engage_kill_switch(
    body: KillSwitchEngageRequest,
    request: Request,
) -> KillSwitchStatusResponse:
    """Engage kill switch — blocks new agent turns until released."""
    principal = require_admin(request)
    resources = get_app_resources(request.app)
    await resources.kill_switch.engage(actor=principal.subject, reason=body.reason)
    return KillSwitchStatusResponse(engaged=True)


@router.post("/kill-switch/release", response_model=KillSwitchStatusResponse)
async def release_kill_switch(request: Request) -> KillSwitchStatusResponse:
    """Release kill switch and allow agent turns again."""
    principal = require_admin(request)
    resources = get_app_resources(request.app)
    await resources.kill_switch.release(actor=principal.subject)
    return KillSwitchStatusResponse(engaged=False)

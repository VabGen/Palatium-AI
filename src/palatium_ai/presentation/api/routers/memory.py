# src/palatium_ai/presentation/api/routers/memory.py

"""User-initiated memory save/forget/consolidate (HITL-gated, off LangGraph hot path)."""

from __future__ import annotations

from typing import Literal

from fastapi import APIRouter, HTTPException, Request, status
from pydantic import BaseModel, Field

from palatium_ai.application.services.hitl_service import HitlInvalidActionError
from palatium_ai.domain.hitl.cards import HITLCardView
from palatium_ai.presentation.resources import get_app_resources
from palatium_ai.presentation.security.deps import get_principal
from palatium_ai.presentation.security.ownership import load_session_for_principal

router = APIRouter()


class MemorySaveRequest(BaseModel):
    """Request to stage a memory write pending HITL approval."""

    model_config = {"frozen": True}

    thread_id: str = Field(min_length=1, max_length=128)
    text: str = Field(min_length=1, max_length=2000)
    entry_key: str = Field(min_length=1, max_length=256)
    namespace_kind: Literal["thread", "user", "org"] = "thread"
    scope_id: str = Field(default="", max_length=128)
    memory_type: Literal["preference", "fact", "incident", "episode"] = "fact"
    contains_pii: bool = False


class MemoryForgetRequest(BaseModel):
    """Request to stage a memory delete pending HITL approval."""

    model_config = {"frozen": True}

    thread_id: str = Field(min_length=1, max_length=128)
    entry_key: str = Field(min_length=1, max_length=256)
    namespace_kind: Literal["thread", "user", "org"] = "thread"
    scope_id: str = Field(default="", max_length=128)


class MemoryConsolidateRequest(BaseModel):
    """Request to stage sleep-time consolidation pending HITL approval."""

    model_config = {"frozen": True}

    thread_id: str = Field(min_length=1, max_length=128)
    consolidate_task_id: str = Field(
        default="",
        max_length=128,
        description="Optional job id for the consolidation queue.",
    )


def _http_error_for_memory_validation(exc: Exception) -> HTTPException:
    detail = str(exc)
    code = (
        status.HTTP_403_FORBIDDEN
        if "must match authenticated" in detail or "requires authenticated org" in detail
        else status.HTTP_400_BAD_REQUEST
    )
    return HTTPException(status_code=code, detail=detail)


@router.post("/save", response_model=HITLCardView)
async def request_memory_save(body: MemorySaveRequest, request: Request) -> HITLCardView:
    """Create HITL card for platform.save_memory; does not write until approve."""
    principal = get_principal(request)
    resources = get_app_resources(request.app)
    if resources.memory_save_service is None:
        raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail="Memory save unavailable")

    await load_session_for_principal(
        request=request,
        principal=principal,
        session_service=resources.session_service,
        thread_id=body.thread_id,
        allow_missing=False,
    )

    try:
        return await resources.memory_save_service.request_save(
            thread_id=body.thread_id,
            owner_user_id=principal.subject,
            org_id=principal.org_id,
            namespace_kind=body.namespace_kind,
            scope_id=body.scope_id,
            entry_key=body.entry_key,
            text=body.text,
            memory_type=body.memory_type,
            contains_pii=body.contains_pii,
        )
    except (ValueError, HitlInvalidActionError) as exc:
        raise _http_error_for_memory_validation(exc) from exc


@router.post("/forget", response_model=HITLCardView)
async def request_memory_forget(body: MemoryForgetRequest, request: Request) -> HITLCardView:
    """Create HITL card for platform.forget_memory; does not delete until approve."""
    principal = get_principal(request)
    resources = get_app_resources(request.app)
    if resources.memory_forget_service is None:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Memory forget unavailable",
        )

    await load_session_for_principal(
        request=request,
        principal=principal,
        session_service=resources.session_service,
        thread_id=body.thread_id,
        allow_missing=False,
    )

    try:
        return await resources.memory_forget_service.request_forget(
            thread_id=body.thread_id,
            owner_user_id=principal.subject,
            org_id=principal.org_id,
            namespace_kind=body.namespace_kind,
            scope_id=body.scope_id,
            entry_key=body.entry_key,
        )
    except (ValueError, HitlInvalidActionError) as exc:
        raise _http_error_for_memory_validation(exc) from exc


@router.post("/consolidate", response_model=HITLCardView)
async def request_memory_consolidate(body: MemoryConsolidateRequest, request: Request) -> HITLCardView:
    """Create HITL card for platform.consolidate_memory; does not enqueue until approve."""
    principal = get_principal(request)
    resources = get_app_resources(request.app)
    if resources.memory_consolidate_service is None:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Memory consolidate unavailable",
        )

    await load_session_for_principal(
        request=request,
        principal=principal,
        session_service=resources.session_service,
        thread_id=body.thread_id,
        allow_missing=False,
    )

    try:
        return await resources.memory_consolidate_service.request_consolidate(
            thread_id=body.thread_id,
            owner_user_id=principal.subject,
            org_id=principal.org_id,
            consolidate_task_id=body.consolidate_task_id,
        )
    except (ValueError, HitlInvalidActionError) as exc:
        raise _http_error_for_memory_validation(exc) from exc

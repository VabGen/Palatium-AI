# src/palatium_ai/presentation/api/routers/intents.py

"""API для классификации намерений."""

from __future__ import annotations

import json

from collections.abc import AsyncIterator
from uuid import UUID

from fastapi import APIRouter, HTTPException, Request, status
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field

from palatium_ai.application.services.cost_budget import CostBudgetExceededError
from palatium_ai.application.services.kill_switch import KillSwitchEngagedError
from palatium_ai.domain.agents.formatter import FormatterTaskResult
from palatium_ai.domain.agents.intent import IntentTaskResult
from palatium_ai.domain.attachments.errors import (
    AttachmentError,
    AttachmentNotFoundError,
    AttachmentNotUsableError,
)
from palatium_ai.domain.sessions.errors import SessionOwnershipError
from palatium_ai.presentation.resources import get_app_resources
from palatium_ai.presentation.security.deps import get_principal, principal_is_admin

router = APIRouter()


class ClassifyIntentRequest(BaseModel):
    """Запрос на классификацию намерения."""

    text: str = Field(min_length=1, max_length=32_000)
    thread_id: str = Field(min_length=1, max_length=128)
    #: Attachments to fold into this turn as fenced untrusted context (020).
    #: Ids must belong to the caller and be ``ready``/``indexed`` already.
    attachment_ids: tuple[UUID, ...] = Field(default_factory=tuple, max_length=5)
    org_id: str | None = Field(
        default=None,
        max_length=128,
        description="Ignored; tenant comes from the JWT principal only.",
    )


def _map_runtime_error(exc: Exception) -> HTTPException:
    if isinstance(exc, KillSwitchEngagedError):
        return HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail=str(exc))
    if isinstance(exc, CostBudgetExceededError):
        return HTTPException(status_code=status.HTTP_402_PAYMENT_REQUIRED, detail=str(exc))
    if isinstance(exc, SessionOwnershipError):
        return HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=str(exc))
    if isinstance(exc, AttachmentNotFoundError):
        return HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc))
    if isinstance(exc, AttachmentNotUsableError):
        return HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc))
    if isinstance(exc, AttachmentError):
        return HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc))
    raise exc


@router.post("/classify", response_model=IntentTaskResult)
async def classify_intent(body: ClassifyIntentRequest, request: Request) -> IntentTaskResult:
    """Классифицирует пользовательскую задачу на platform-level task kind."""
    principal = get_principal(request)
    resources = get_app_resources(request.app)
    try:
        return await resources.intent_service.classify(
            text=body.text,
            thread_id=body.thread_id,
            user_id=principal.subject,
            org_id=principal.org_id,
            is_admin=principal_is_admin(request, principal),
            attachment_ids=list(body.attachment_ids),
        )
    except (
        KillSwitchEngagedError,
        CostBudgetExceededError,
        SessionOwnershipError,
        AttachmentError,
    ) as exc:
        raise _map_runtime_error(exc) from exc


@router.post("/process", response_model=FormatterTaskResult)
async def process_intent(body: ClassifyIntentRequest, request: Request) -> FormatterTaskResult:
    """Прогоняет полный конвейер и возвращает финально отформатированный ответ."""
    principal = get_principal(request)
    resources = get_app_resources(request.app)
    try:
        return await resources.intent_service.process(
            text=body.text,
            thread_id=body.thread_id,
            user_id=principal.subject,
            org_id=principal.org_id,
            is_admin=principal_is_admin(request, principal),
            attachment_ids=list(body.attachment_ids),
        )
    except (
        KillSwitchEngagedError,
        CostBudgetExceededError,
        SessionOwnershipError,
        AttachmentError,
    ) as exc:
        raise _map_runtime_error(exc) from exc


@router.post("/process/stream")
async def process_intent_stream(body: ClassifyIntentRequest, request: Request) -> StreamingResponse:
    """SSE stream: hop progress events, then a final ``result`` with FormatterTaskResult."""
    principal = get_principal(request)
    resources = get_app_resources(request.app)

    async def event_gen() -> AsyncIterator[str]:
        try:
            async for event in resources.intent_service.process_stream(
                text=body.text,
                thread_id=body.thread_id,
                user_id=principal.subject,
                org_id=principal.org_id,
                is_admin=principal_is_admin(request, principal),
                attachment_ids=list(body.attachment_ids),
            ):
                name = str(event.get("event", "message"))
                payload = {k: v for k, v in event.items() if k != "event"}
                yield f"event: {name}\ndata: {json.dumps(payload, ensure_ascii=False)}\n\n"
        except (
            KillSwitchEngagedError,
            CostBudgetExceededError,
            SessionOwnershipError,
            AttachmentError,
        ) as exc:
            mapped = _map_runtime_error(exc)
            err_payload = json.dumps(
                {"detail": mapped.detail, "status_code": mapped.status_code},
                ensure_ascii=False,
            )
            yield f"event: error\ndata: {err_payload}\n\n"

    return StreamingResponse(
        event_gen(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )

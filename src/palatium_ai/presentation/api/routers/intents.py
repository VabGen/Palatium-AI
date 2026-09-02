# src/palatium_ai/presentation/api/routers/intents.py

"""API для классификации намерений."""

from __future__ import annotations

from fastapi import APIRouter, HTTPException, Request, status
from pydantic import BaseModel, Field

from palatium_ai.application.services.cost_budget import CostBudgetExceededError
from palatium_ai.application.services.kill_switch import KillSwitchEngagedError
from palatium_ai.domain.agents.formatter import FormatterTaskResult
from palatium_ai.domain.agents.intent import IntentTaskResult
from palatium_ai.domain.sessions.errors import SessionOwnershipError
from palatium_ai.presentation.resources import get_app_resources
from palatium_ai.presentation.security.deps import get_principal, principal_is_admin

router = APIRouter()


class ClassifyIntentRequest(BaseModel):
    """Запрос на классификацию намерения."""

    text: str = Field(min_length=1, max_length=32_000)
    thread_id: str = Field(min_length=1, max_length=128)
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
        )
    except (KillSwitchEngagedError, CostBudgetExceededError, SessionOwnershipError) as exc:
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
        )
    except (KillSwitchEngagedError, CostBudgetExceededError, SessionOwnershipError) as exc:
        raise _map_runtime_error(exc) from exc

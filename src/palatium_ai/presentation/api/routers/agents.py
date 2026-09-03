# src/palatium_ai/presentation/api/routers/agents.py

"""API-роуты для управления агентами."""

from fastapi import APIRouter, Request

from palatium_ai.presentation.security.deps import require_admin

router = APIRouter()


@router.get("/")
async def list_agents(request: Request) -> dict[str, list[str]]:
    """Admin-only roster stub (do not expose agent topology to every JWT)."""
    _ = require_admin(request)
    return {
        "agents": [
            "context_enricher",
            "intent_classifier",
            "supervisor",
            "researcher",
            "critic",
            "formatter",
            "memory_keeper",
        ]
    }


@router.get("/health")
async def agents_health() -> dict[str, str]:
    """Health-check эндпоинт слоя агентов (JWT required by AuthMiddleware)."""
    return {"status": "ok"}

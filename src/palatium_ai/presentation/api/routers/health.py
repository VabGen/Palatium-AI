# src/palatium_ai/presentation/api/routers/health.py

"""Health / readiness роуты приложения."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter

from palatium_ai.core.config import get_settings

router = APIRouter()


@router.get("/health")
async def health() -> dict[str, str]:
    """Глобальный health-check приложения (liveness)."""
    return {"status": "ok"}


@router.get("/ready")
async def ready() -> dict[str, Any]:
    """Readiness: memory / graph backend expectations for staging/prod (SB4).

    Always returns HTTP 200 with ``status`` ok|degraded so probes can parse body
    without treating a misconfigured local graph as a crash-loop. Operators gate
    on ``status == ok`` in staging/prod (ops-readiness / ops_probe).
    """
    settings = get_settings()
    env = settings.app.environment
    graph_backend = settings.memory.graph_query_backend
    memory_backend = settings.memory.backend
    checks: dict[str, object] = {
        "environment": env,
        "memory_backend": memory_backend,
        "graph_query_backend": graph_backend,
        "promote_enabled": settings.memory.promote_enabled,
    }
    warnings: list[str] = []
    if env in {"staging", "production"}:
        if graph_backend != "neo4j":
            warnings.append(f"GRAPH_QUERY_BACKEND should be neo4j in staging/production (got {graph_backend!r})")
        if memory_backend != "postgres":
            warnings.append(f"MEMORY_BACKEND should be postgres in staging/production (got {memory_backend!r})")
    status = "ok" if not warnings else "degraded"
    return {
        "status": status,
        "checks": checks,
        "warnings": warnings,
    }

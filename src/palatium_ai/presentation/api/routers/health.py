# src/palatium_ai/presentation/api/routers/health.py

"""Health-check роуты приложения."""

from fastapi import APIRouter

router = APIRouter()


@router.get("/health")
async def health() -> dict[str, str]:
    """Глобальный health-check приложения."""
    return {"status": "ok"}

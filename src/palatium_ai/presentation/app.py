# src/palatium_ai/presentation/app.py

"""Фабрика FastAPI-приложения."""

from __future__ import annotations

from contextlib import asynccontextmanager
from pathlib import Path
from typing import TYPE_CHECKING

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles

from palatium_ai.application.bootstrap import shutdown, startup
from palatium_ai.core.config import get_settings
from palatium_ai.presentation.api.routers import (
    admin,
    agents,
    auth,
    documents,
    feedback,
    health,
    hitl,
    intents,
    metrics,
    sessions,
)
from palatium_ai.presentation.middleware.auth import AuthMiddleware
from palatium_ai.presentation.middleware.rate_limit import RateLimitMiddleware
from palatium_ai.presentation.security.jwt import JwtTokenService

if TYPE_CHECKING:
    from collections.abc import AsyncIterator

    from palatium_ai.core.config.settings import Settings

_REPO_ROOT = Path(__file__).resolve().parents[3]
_UI_DIST = _REPO_ROOT / "web" / "dist"


def create_app(settings: Settings | None = None) -> FastAPI:
    """Создаёт и конфигурирует экземпляр FastAPI."""
    resolved_settings = settings or get_settings()
    resolved_settings.security.require_auth_material()
    _assert_environment_hardening(resolved_settings)
    token_service = JwtTokenService(resolved_settings.security)

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        resources = await startup(resolved_settings)
        app.state.resources = resources
        yield
        await shutdown(resources)

    application = FastAPI(
        title=resolved_settings.app.name,
        version=resolved_settings.app.version,
        lifespan=lifespan,
    )
    application.state.settings = resolved_settings
    application.state.security_config = resolved_settings.security
    application.state.token_service = token_service

    # Middleware order: last added runs first on the request path.
    application.add_middleware(
        RateLimitMiddleware,
        limit=resolved_settings.security.api_rate_limit,
        window_seconds=resolved_settings.security.api_rate_limit_window_seconds,
        path_prefixes=resolved_settings.security.rate_limit_path_prefixes,
    )
    metrics_public = (
        resolved_settings.security.metrics_public if resolved_settings.app.environment == "development" else False
    )
    application.add_middleware(
        AuthMiddleware,
        security=resolved_settings.security,
        token_service=token_service,
        metrics_public=metrics_public,
    )
    cors_origins = list(resolved_settings.security.cors_origin_list)
    if not cors_origins:
        raise RuntimeError("CORS_ORIGINS must list at least one origin (wildcards are forbidden)")
    application.add_middleware(
        CORSMiddleware,
        allow_origins=cors_origins,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    application.include_router(auth.router, prefix="/api/auth", tags=["auth"])
    application.include_router(admin.router, prefix="/api/admin", tags=["admin"])
    application.include_router(agents.router, prefix="/api/agents", tags=["agents"])
    application.include_router(sessions.router, prefix="/api/sessions", tags=["sessions"])
    application.include_router(intents.router, prefix="/api/intents", tags=["intents"])
    application.include_router(hitl.router, prefix="/api/hitl", tags=["hitl"])
    application.include_router(documents.router, prefix="/api/documents", tags=["documents"])
    application.include_router(health.router, tags=["health"])
    application.include_router(metrics.router, tags=["observability"])
    application.include_router(feedback.router, prefix="/api", tags=["feedback"])

    _mount_chat_ui(application)

    return application


def _assert_environment_hardening(settings: Settings) -> None:
    """Fail closed on staging/production Zero Trust / SLA knobs."""
    if settings.app.environment not in {"staging", "production"}:
        return
    if not settings.security.auth_enabled:
        raise RuntimeError("AUTH_ENABLED must be true when ENVIRONMENT is staging or production")
    if settings.observability.turn_cost_budget_usd <= 0:
        raise RuntimeError("TURN_COST_BUDGET_USD must be > 0 when ENVIRONMENT is staging or production")
    if settings.observability.daily_cost_budget_usd <= 0:
        raise RuntimeError("DAILY_COST_BUDGET_USD must be > 0 when ENVIRONMENT is staging or production")
    chain = settings.llm.build_provider_chain(settings.llm.default_provider)
    if len(chain) < 2:
        raise RuntimeError(
            "LLM_FALLBACK_PROVIDERS must yield ≥1 distinct fallback "
            "(provider chain length ≥2) when ENVIRONMENT is staging or production"
        )
    step_up_method = getattr(settings.security, "hitl_step_up_method", "hmac_stub")
    if step_up_method == "hmac_stub":
        raise RuntimeError(
            "HITL_STEP_UP_METHOD=hmac_stub is forbidden when ENVIRONMENT is staging or production "
            "(use idp_acr or webauthn)"
        )


def _mount_chat_ui(application: FastAPI) -> None:
    """Подключает собранный chat shell (web/dist) на /ui."""
    if not _UI_DIST.is_dir() or not (_UI_DIST / "index.html").is_file():
        return

    assets_dir = _UI_DIST / "assets"
    if assets_dir.is_dir():
        application.mount(
            "/ui/assets",
            StaticFiles(directory=assets_dir),
            name="ui-assets",
        )

    @application.get("/ui", include_in_schema=False)
    @application.get("/ui/", include_in_schema=False)
    @application.get("/ui/{path:path}", include_in_schema=False)
    async def chat_ui(path: str = "") -> FileResponse:
        _ = path
        return FileResponse(_UI_DIST / "index.html")

    @application.get("/", include_in_schema=False)
    async def root_to_ui() -> RedirectResponse:
        return RedirectResponse(url="/ui/")

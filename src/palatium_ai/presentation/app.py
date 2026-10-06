# src/palatium_ai/presentation/app.py

"""Фабрика FastAPI-приложения."""

from __future__ import annotations

from collections.abc import Mapping
from contextlib import asynccontextmanager
from datetime import UTC, datetime
from pathlib import Path
from typing import TYPE_CHECKING, Any, cast
from urllib.parse import urlsplit

import structlog

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles

from palatium_ai.application.bootstrap import shutdown, startup
from palatium_ai.core.config import get_settings
from palatium_ai.core.exceptions import AuditChainIntegrityError, AuditWriteDegradedError, DatabaseUnavailableError
from palatium_ai.core.logging.context import trace_id_var
from palatium_ai.core.observability import get_audit_logger
from palatium_ai.core.observability.metrics import agent_metrics
from palatium_ai.presentation.api.routers import (
    admin,
    agents,
    attachments,
    auth,
    documents,
    feedback,
    health,
    hitl,
    intents,
    memory,
    metrics,
    sessions,
)
from palatium_ai.presentation.middleware.auth import AuthMiddleware
from palatium_ai.presentation.middleware.rate_limit import RateLimitMiddleware
from palatium_ai.presentation.middleware.tracing import TracingMiddleware
from palatium_ai.presentation.security.jwt import JwtTokenService
from palatium_ai.presentation.websockets.session import register_websocket_routes

if TYPE_CHECKING:
    from collections.abc import AsyncIterator

    from palatium_ai.core.config.settings import Settings

_REPO_ROOT = Path(__file__).resolve().parents[3]
_UI_DIST = _REPO_ROOT / "web" / "dist"

logger = structlog.get_logger(__name__)


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
    register_error_handlers(application)

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
    application.add_middleware(TracingMiddleware)

    application.include_router(auth.router, prefix="/api/auth", tags=["auth"])
    application.include_router(admin.router, prefix="/api/admin", tags=["admin"])
    application.include_router(agents.router, prefix="/api/agents", tags=["agents"])
    application.include_router(sessions.router, prefix="/api/sessions", tags=["sessions"])
    application.include_router(intents.router, prefix="/api/intents", tags=["intents"])
    application.include_router(hitl.router, prefix="/api/hitl", tags=["hitl"])
    application.include_router(documents.router, prefix="/api/documents", tags=["documents"])
    application.include_router(attachments.router, prefix="/api/attachments", tags=["attachments"])
    application.include_router(memory.router, prefix="/api/memory", tags=["memory"])
    application.include_router(health.router, tags=["health"])
    application.include_router(metrics.router, tags=["observability"])
    application.include_router(feedback.router, prefix="/api", tags=["feedback"])

    _mount_chat_ui(application)
    register_websocket_routes(application)

    return application


# ────────────────────────────────────────────────────────────────────────────
# Error handlers
# ────────────────────────────────────────────────────────────────────────────


def register_error_handlers(application: FastAPI) -> None:
    """Map typed boundary errors onto external status codes (035)."""
    application.add_exception_handler(DatabaseUnavailableError, database_unavailable_handler)
    application.add_exception_handler(RequestValidationError, validation_error_handler)


async def database_unavailable_handler(request: Request, exc: Exception) -> JSONResponse:
    """Answer ``503`` + ``Retry-After`` when the DB layer exhausted its retry budget (035).

    The request never executed, so a retry is safe; the internal cause (driver class,
    DSN, SQL) stays in the log and metric and never reaches the response body.
    """
    unavailable = cast("DatabaseUnavailableError", exc)
    retry_after = max(1, unavailable.retry_after_seconds)
    agent_metrics.record_error("database", "unavailable")
    logger.warning(
        "db.unavailable",
        path=request.url.path,
        method=request.method,
        operation=unavailable.operation,
        retry_after_seconds=retry_after,
    )
    await _audit_db_unavailable(request, unavailable)
    return JSONResponse(
        status_code=503,
        content={"detail": "Database temporarily unavailable, please retry shortly"},
        headers={"Retry-After": str(retry_after)},
    )


async def _audit_db_unavailable(request: Request, exc: DatabaseUnavailableError) -> None:
    """Audit the fail-closed boundary (035) — best effort, never masking the 503."""
    try:
        await get_audit_logger().append_async(
            timestamp=datetime.now(UTC).isoformat(),
            conversation_id=f"http:{request.method}:{request.url.path}",
            event="db_unavailable",
            metadata={
                "operation": exc.operation,
                "retry_after_seconds": str(exc.retry_after_seconds),
                "http_status": "503",
                "trace_id": trace_id_var.get() or "unknown",
            },
        )
    except (AuditWriteDegradedError, AuditChainIntegrityError, OSError) as audit_exc:
        logger.warning(
            "db.unavailable.audit_skipped",
            path=request.url.path,
            error_type=type(audit_exc).__name__,
        )


# ────────────────────────────────────────────────────────────────────────────
# Validation handler (422 → human-readable)
# ────────────────────────────────────────────────────────────────────────────


def _humanize_pydantic_error(err: Mapping[str, Any]) -> dict[str, object]:
    """Преобразует одну Pydantic-ошибку в короткое сообщение для клиента.

    Формат ответа (разбирает `web/src/api/client.ts::humanizePydanticError`):
        {"field": "...", "code": "...", "message": "..."}
    """
    loc_raw = err.get("loc")
    loc: tuple[Any, ...] | list[Any] = loc_raw if isinstance(loc_raw, (list, tuple)) else ()
    field = str(loc[-1]) if loc else "body"
    etype = str(err.get("type", "unknown"))
    ctx_raw = err.get("ctx")
    ctx: Mapping[str, Any] = ctx_raw if isinstance(ctx_raw, Mapping) else {}

    if etype == "string_too_long":
        limit = ctx.get("max_length", "?")
        return {
            "field": field,
            "code": "too_long",
            "message": f"«{field}»: максимум {limit} символов",
        }
    if etype == "string_too_short":
        min_length = ctx.get("min_length", 1)
        suffix = "" if min_length == 1 else "а"
        return {
            "field": field,
            "code": "too_short",
            "message": f"«{field}»: минимум {min_length} символ{suffix}",
        }
    if etype == "too_long":
        limit = ctx.get("max_length", "?")
        return {
            "field": field,
            "code": "too_many_items",
            "message": f"«{field}»: максимум {limit} элементов",
        }
    if etype == "uuid_parsing":
        return {
            "field": field,
            "code": "invalid_uuid",
            "message": f"«{field}»: некорректный UUID",
        }
    if etype == "missing":
        return {
            "field": field,
            "code": "required",
            "message": f"«{field}»: обязательное поле",
        }

    return {
        "field": field,
        "code": etype,
        "message": str(err.get("msg") or etype),
    }


def validation_error_handler(request: Request, exc: Exception) -> JSONResponse:
    """Human-readable 422 for all clients (web, mobile, integrations).

    FastAPI's default response embeds a raw Pydantic dump — useless in a UI. We
    convert it into ``{"detail": [{"field", "code", "message"}]}``, which the
    frontend renders verbatim. The shape is a stable contract for API consumers.

    Sync on purpose: no awaits inside; ``async def`` would trip ``RUF029``.
    Starlette accepts sync handlers for both ``HTTPException`` and
    ``RequestValidationError``.
    """
    validation_exc = cast("RequestValidationError", exc)
    issues = [_humanize_pydantic_error(err) for err in validation_exc.errors()]
    logger.info(
        "request.validation_failed",
        path=request.url.path,
        method=request.method,
        issues_count=len(issues),
    )
    return JSONResponse(status_code=422, content={"detail": issues})


# ────────────────────────────────────────────────────────────────────────────
# Environment hardening
# ────────────────────────────────────────────────────────────────────────────


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
    # 020 / 055: symmetric JWT in a hardened environment is a shared-secret footgun — require
    # asymmetric signing/verification (JWKS). Default HS256 must not silently reach production.
    algorithm = str(settings.security.jwt_algorithm).strip().upper()
    if algorithm.startswith("HS"):
        raise RuntimeError("JWT_ALGORITHM must be asymmetric (RS*/ES*) when ENVIRONMENT is staging or production")
    # 020: allowed origins are an explicit allow-list; loopback defaults must not leak into a hardened env.
    loopback = tuple(origin for origin in settings.security.cors_origin_list if _is_loopback_origin(origin))
    if loopback:
        raise RuntimeError(
            f"CORS_ORIGINS must not include loopback origins {loopback!r} when ENVIRONMENT is staging or production"
        )
    # 020: HITL action tokens are HMAC even with asymmetric JWT — require a non-trivial key.
    hitl_secret = getattr(settings.security, "hitl_signing_secret", None)
    if hitl_secret is not None and 0 < len(hitl_secret.get_secret_value().strip()) < 32:
        raise RuntimeError(
            "HITL_SIGNING_SECRET must be at least 32 characters when ENVIRONMENT is staging or production"
        )


_LOOPBACK_HOSTS = frozenset({"localhost", "127.0.0.1", "0.0.0.0", "::1"})  # noqa: S104 — CORS origin allowlist, not a bind address


def _is_loopback_origin(origin: str) -> bool:
    """True when a CORS origin resolves to a loopback/any-local host (020)."""
    host = (urlsplit(origin).hostname or "").strip().lower()
    return host in _LOOPBACK_HOSTS or host.endswith(".localhost")


# ────────────────────────────────────────────────────────────────────────────
# Chat UI mount
# ────────────────────────────────────────────────────────────────────────────


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

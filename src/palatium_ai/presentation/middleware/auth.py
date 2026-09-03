# src/palatium_ai/presentation/middleware/auth.py

"""Bearer JWT authentication middleware for /api/*."""

from __future__ import annotations

from typing import TYPE_CHECKING

from starlette.middleware.base import BaseHTTPMiddleware, RequestResponseEndpoint
from starlette.responses import JSONResponse

from palatium_ai.core.logging.context import user_id_var
from palatium_ai.presentation.security.jwt import JwtTokenService, JwtValidationError
from palatium_ai.presentation.security.principal import AuthPrincipal

if TYPE_CHECKING:
    from starlette.requests import Request
    from starlette.responses import Response
    from starlette.types import ASGIApp

    from palatium_ai.core.config.security import SecurityConfig

_PUBLIC_EXACT = frozenset(
    {
        "/health",
        "/docs",
        "/redoc",
        "/openapi.json",
        "/",
    }
)
_PUBLIC_PREFIXES = ("/ui", "/docs/", "/redoc/")
_PUBLIC_API_POST = frozenset({"/api/auth/dev-token"})
_PUBLIC_API_GET = frozenset({"/api/auth/dev-hitl-step-up"})


class AuthMiddleware(BaseHTTPMiddleware):
    """Attach `request.state.principal` after verifying Authorization bearer JWT."""

    def __init__(
        self,
        app: ASGIApp,
        *,
        security: SecurityConfig,
        token_service: JwtTokenService,
        metrics_public: bool = True,
    ) -> None:
        super().__init__(app)
        self._security = security
        self._tokens = token_service
        self._metrics_public = metrics_public

    async def dispatch(self, request: Request, call_next: RequestResponseEndpoint) -> Response:
        """Verify bearer JWT for /api/* and attach principal to request.state."""
        if _is_public(request.url.path, request.method, metrics_public=self._metrics_public):
            return await call_next(request)

        if request.url.path == "/metrics":
            return await self._dispatch_authenticated(request, call_next)

        if not request.url.path.startswith("/api/"):
            return await call_next(request)

        return await self._dispatch_authenticated(request, call_next)

    async def _dispatch_authenticated(
        self,
        request: Request,
        call_next: RequestResponseEndpoint,
    ) -> Response:
        if not self._security.auth_enabled:
            request.state.principal = AuthPrincipal(subject="anonymous", roles=frozenset())
            user_token = user_id_var.set("anonymous")
            try:
                return await call_next(request)
            finally:
                user_id_var.reset(user_token)

        header = request.headers.get("Authorization")
        if header is None or not header.lower().startswith("bearer "):
            return _unauthorized("Missing bearer token")
        token = header[7:].strip()
        if not token:
            return _unauthorized("Empty bearer token")

        try:
            principal = self._tokens.verify_bearer(token)
        except JwtValidationError as exc:
            return _unauthorized(str(exc))

        request.state.principal = principal
        user_token = user_id_var.set(principal.subject)
        try:
            return await call_next(request)
        finally:
            user_id_var.reset(user_token)


def _is_public(path: str, method: str, *, metrics_public: bool) -> bool:
    if path == "/metrics":
        return metrics_public
    if path in _PUBLIC_EXACT:
        return True
    if any(path.startswith(prefix) for prefix in _PUBLIC_PREFIXES):
        return True
    method_u = method.upper()
    if path in _PUBLIC_API_POST and method_u == "POST":
        return True
    return path in _PUBLIC_API_GET and method_u == "GET"


def _unauthorized(detail: str) -> JSONResponse:
    return JSONResponse(
        status_code=401,
        content={"detail": detail},
        headers={"WWW-Authenticate": "Bearer"},
    )

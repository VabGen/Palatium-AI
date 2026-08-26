# src/palatium_ai/presentation/security/deps.py

"""FastAPI dependencies for authenticated principals."""

from __future__ import annotations

from fastapi import HTTPException, Request, status

from palatium_ai.presentation.security.principal import AuthPrincipal


def get_principal(request: Request) -> AuthPrincipal:
    """Return the principal attached by AuthMiddleware."""
    principal = getattr(request.state, "principal", None)
    if not isinstance(principal, AuthPrincipal):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Authentication required",
            headers={"WWW-Authenticate": "Bearer"},
        )
    return principal


def require_admin(request: Request) -> AuthPrincipal:
    """Require an admin role on the current principal."""
    principal = get_principal(request)
    security = request.app.state.security_config
    admin_roles = security.admin_role_set
    if not principal.has_any_role(admin_roles):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Admin role required",
        )
    return principal


def require_manager(request: Request) -> AuthPrincipal:
    """Require a manager (or admin) role for HITL escalation queue."""
    principal = get_principal(request)
    security = request.app.state.security_config
    if not principal.has_any_role(security.manager_role_set):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Manager role required",
        )
    return principal


def principal_is_admin(request: Request, principal: AuthPrincipal) -> bool:
    """Return whether principal matches configured admin roles."""
    security = request.app.state.security_config
    return principal.has_any_role(security.admin_role_set)

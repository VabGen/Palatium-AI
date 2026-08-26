# src/palatium_ai/presentation/security/__init__.py

"""Presentation-layer auth helpers (JWT principal, ownership, rate limit)."""

from palatium_ai.presentation.security.deps import get_principal, require_admin
from palatium_ai.presentation.security.ownership import assert_session_access
from palatium_ai.presentation.security.principal import AuthPrincipal

__all__ = [
    "AuthPrincipal",
    "assert_session_access",
    "get_principal",
    "require_admin",
]

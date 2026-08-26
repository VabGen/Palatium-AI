# src/palatium_ai/presentation/security/principal.py

"""Authenticated request principal."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class AuthPrincipal:
    """Identity extracted from a verified JWT (or disabled-auth fallback)."""

    subject: str
    roles: frozenset[str]
    org_id: str | None = None
    token_id: str | None = None

    def has_any_role(self, allowed: frozenset[str]) -> bool:
        """Return True when principal carries at least one allowed role."""
        if not allowed:
            return False
        return bool(self.roles & allowed)

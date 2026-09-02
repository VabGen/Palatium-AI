# src/palatium_ai/domain/sessions/errors.py

"""Domain errors for session ownership (no core/infra imports)."""

from __future__ import annotations


class SessionOwnershipError(PermissionError):
    """Caller is not the session owner (and is not admin)."""

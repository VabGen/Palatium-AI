"""Ownership policy for conversation threads.

Presentation GET helpers and IntentService mutate-path share the same core rule:
a bound owner cannot be replaced except by admin.

Existing unowned sessions (`user_id is None`) are admin-only. Allowing a stranger
to claim them would transfer residual MCP / dialog payloads (IDOR). Fresh threads
use `allow_missing=True` and bind owner on first touch.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

from palatium_ai.domain.sessions.errors import SessionOwnershipError

AccessVerdict = Literal["allow", "deny", "claim"]


@dataclass(frozen=True, slots=True)
class SessionAccessDecision:
    """Outcome of evaluate_session_access."""

    verdict: AccessVerdict
    reason: str

    @property
    def allowed(self) -> bool:
        """True when the caller may read or continue the thread."""
        return self.verdict in {"allow", "claim"}


def evaluate_session_access(
    *,
    owner_user_id: str | None,
    caller_user_id: str | None,
    is_admin: bool = False,
    allow_missing: bool = False,
    session_exists: bool = True,
    allow_claim: bool = False,
) -> SessionAccessDecision:
    """Decide whether caller may use this thread (not a phrase/UX special case).

    `allow_claim` is retained for call-site compatibility but never grants access to
    an existing unowned session — residual data stays admin-only.
    """
    _ = allow_claim
    if not session_exists:
        if allow_missing:
            return SessionAccessDecision("allow", "missing_thread_may_be_created")
        return SessionAccessDecision("deny", "session_not_found")
    if is_admin:
        return SessionAccessDecision("allow", "admin")
    if owner_user_id is None:
        return SessionAccessDecision("deny", "unowned_not_readable")
    if caller_user_id is None or owner_user_id != caller_user_id:
        return SessionAccessDecision("deny", "owner_mismatch")
    return SessionAccessDecision("allow", "owner")


def next_session_owner(*, existing_owner: str | None, incoming_user_id: str | None) -> str | None:
    """Return the owner to persist. Never overwrite a different bound owner."""
    if existing_owner is not None and incoming_user_id is not None and existing_owner != incoming_user_id:
        raise SessionOwnershipError(
            "Not allowed to bind this session to a different user",
        )
    if existing_owner is None:
        return incoming_user_id
    return existing_owner

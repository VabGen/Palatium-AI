# src/palatium_ai/domain/hitl/action_tokens.py

"""HMAC action tokens binding HITL clicks to card, expiry, subject, and nonce."""

from __future__ import annotations

import hashlib
import hmac

from datetime import UTC, datetime
from uuid import uuid4

# Subject used when re-stamping options for the manager escalation queue.
MANAGER_TOKEN_SUBJECT = "role:manager"  # noqa: S105


def new_token_nonce() -> str:
    """Opaque one-time binding material for action tokens."""
    return uuid4().hex


def mint_action_token(
    *,
    secret: str,
    card_id: str,
    action_id: str,
    expires_at: datetime,
    subject: str,
    nonce: str,
) -> str:
    """Create a hex HMAC token (hitl.v2) for one HITL option."""
    payload = _canonical_payload_v2(
        card_id=card_id,
        action_id=action_id,
        expires_at=expires_at,
        subject=subject,
        nonce=nonce,
    )
    digest = hmac.new(secret.encode("utf-8"), payload.encode("utf-8"), hashlib.sha256).hexdigest()
    return digest


def verify_action_token(
    *,
    secret: str,
    token: str,
    card_id: str,
    action_id: str,
    expires_at: datetime,
    subject: str,
    nonce: str,
) -> bool:
    """Constant-time check that token matches the v2 binding."""
    if not token or not secret or not nonce:
        return False
    expected = mint_action_token(
        secret=secret,
        card_id=card_id,
        action_id=action_id,
        expires_at=expires_at,
        subject=subject,
        nonce=nonce,
    )
    return hmac.compare_digest(expected, token)


def _canonical_payload_v2(
    *,
    card_id: str,
    action_id: str,
    expires_at: datetime,
    subject: str,
    nonce: str,
) -> str:
    aware = expires_at if expires_at.tzinfo is not None else expires_at.replace(tzinfo=UTC)
    exp = aware.astimezone(UTC).isoformat()
    sub = subject.strip() or "-"
    return f"hitl.v2|{card_id}|{action_id}|{exp}|{sub}|{nonce}"

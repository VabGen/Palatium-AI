# src/palatium_ai/domain/hitl/step_up.py

"""Step-up (MFA / WebAuthn / IdP ACR) gate for high-risk MCP HITL approvals."""

from __future__ import annotations

import hashlib
import hmac

from typing import TYPE_CHECKING, Literal, Protocol

from pydantic import BaseModel, Field

if TYPE_CHECKING:
    from palatium_ai.domain.hitl.cards import HITLCardView

HitlStepUpMethod = Literal["none", "hmac_stub", "idp_acr", "webauthn"]


class HitlStepUpVerifierPort(Protocol):
    """Verify a step-up assertion (kept for callers that only need verify)."""

    def verify(
        self,
        *,
        card_id: str,
        subject: str,
        assertion: str,
    ) -> bool:
        """Return True when assertion proves recent step-up for this card+subject."""


class HitlStepUpProviderPort(Protocol):
    """Issue + verify step-up ceremonies (HMAC stub / IdP ACR / WebAuthn-backed IdP)."""

    @property
    def method(self) -> HitlStepUpMethod:
        """Configured ceremony method for this deployment."""

    def issue_challenge(self, *, card_id: str, subject: str) -> HitlStepUpChallenge:
        """Return challenge metadata (and HMAC assertion only for local stub)."""

    def verify(
        self,
        *,
        card_id: str,
        subject: str,
        assertion: str,
    ) -> bool:
        """Return True when assertion proves recent step-up for this card+subject."""


class HitlStepUpChallenge(BaseModel):
    """Result of a step-up challenge ceremony."""

    model_config = {"frozen": True}

    required: bool
    method: HitlStepUpMethod = "none"
    assertion: str | None = Field(
        default=None,
        max_length=4096,
        description="Pre-minted only for hmac_stub; IdP/WebAuthn leave null — client supplies JWT.",
    )
    challenge: str | None = Field(
        default=None,
        max_length=512,
        description="Opaque nonce/hint the client forwards to IdP / WebAuthn ceremony.",
    )
    required_acr: str | None = Field(default=None, max_length=256)
    required_amr: tuple[str, ...] = ()
    card_claim: str | None = Field(
        default=None,
        max_length=64,
        description="JWT claim that must equal card_id (card binding).",
    )
    authorize_url: str | None = Field(
        default=None,
        max_length=2048,
        description="Optional IdP/WebAuthn start URL rendered from HITL_STEP_UP_AUTHORIZE_URL.",
    )
    card_id: str = Field(min_length=1, max_length=64)


def render_step_up_authorize_url(
    template: str,
    *,
    card_id: str,
    subject: str,
    challenge: str,
    required_acr: str,
    card_claim: str,
    method: HitlStepUpMethod,
) -> str | None:
    """Fill authorize URL template; empty template → None. No phrase/UX hardcodes."""
    from urllib.parse import quote

    cleaned = template.strip()
    if not cleaned:
        return None
    if not (cleaned.startswith("https://") or cleaned.startswith("http://")):
        raise ValueError("HITL_STEP_UP_AUTHORIZE_URL must be http(s)")
    return cleaned.format(
        card_id=quote(card_id, safe=""),
        subject=quote(subject, safe=""),
        challenge=quote(challenge, safe=""),
        required_acr=quote(required_acr, safe=""),
        card_claim=quote(card_claim, safe=""),
        method=quote(method, safe=""),
    )


class HitlStepUpPolicy:
    """When owner resolve of mcp_tool_approval requires an extra proof factor."""

    # Align with high MCP tier (~0.85) and above CONFIRM_FLOOR.
    MIN_RISK = 0.7

    @classmethod
    def required_for(cls, card: HITLCardView) -> bool:
        """Return True when high-risk pending MCP approval needs step-up."""
        return card.purpose == "mcp_tool_approval" and card.status == "pending" and card.risk_score >= cls.MIN_RISK


def mint_hmac_step_up_assertion(
    *,
    secret: str,
    card_id: str,
    subject: str,
) -> str:
    """Mint a local/dev stand-in for IdP/WebAuthn (not for staging/production)."""
    payload = f"hitl.step_up.v1|{card_id}|{subject.strip() or '-'}"
    return hmac.new(secret.encode("utf-8"), payload.encode("utf-8"), hashlib.sha256).hexdigest()


class HmacHitlStepUpVerifier:
    """HMAC stub verifier — local/dev only; swap provider in staging/production."""

    method: HitlStepUpMethod = "hmac_stub"

    def __init__(self, secret: str) -> None:
        value = secret.strip()
        if len(value) < 16:
            raise ValueError("HITL step-up HMAC secret must be at least 16 characters")
        self._secret = value

    def issue_challenge(self, *, card_id: str, subject: str) -> HitlStepUpChallenge:
        """Pre-mint HMAC assertion for smoke/UI without an IdP."""
        return HitlStepUpChallenge(
            required=True,
            method="hmac_stub",
            assertion=mint_hmac_step_up_assertion(
                secret=self._secret,
                card_id=card_id,
                subject=subject,
            ),
            challenge=None,
            card_id=card_id,
        )

    def verify(self, *, card_id: str, subject: str, assertion: str) -> bool:
        """Return True when HMAC assertion matches card+subject binding."""
        if not assertion or not card_id:
            return False
        expected = mint_hmac_step_up_assertion(
            secret=self._secret,
            card_id=card_id,
            subject=subject,
        )
        return hmac.compare_digest(expected, assertion)

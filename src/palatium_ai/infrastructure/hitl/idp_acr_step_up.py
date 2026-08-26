# src/palatium_ai/infrastructure/hitl/idp_acr_step_up.py

"""IdP ACR / WebAuthn-backed step-up: verify elevated JWT assertions (no HMAC stub)."""

from __future__ import annotations

import secrets
import time

from collections.abc import Callable, Mapping
from typing import Any, Literal

import jwt

from palatium_ai.domain.hitl.step_up import HitlStepUpChallenge, HitlStepUpMethod, render_step_up_authorize_url

ClaimsDecoder = Callable[[str], Mapping[str, Any]]


def _as_str_set(value: object) -> frozenset[str]:
    if value is None:
        return frozenset()
    if isinstance(value, str):
        return frozenset(part.strip() for part in value.replace(" ", ",").split(",") if part.strip())
    if isinstance(value, (list, tuple, set, frozenset)):
        return frozenset(str(item).strip() for item in value if str(item).strip())
    return frozenset()


def _acr_matches(acr_raw: object, required: frozenset[str]) -> bool:
    return bool(_as_str_set(acr_raw) & required) or (isinstance(acr_raw, str) and acr_raw.strip() in required)


def _fresh_enough(claims: Mapping[str, Any], *, now: int, max_age: int) -> bool:
    iat = claims.get("iat")
    if isinstance(iat, (int, float)) and now - int(iat) > max_age:
        return False
    exp = claims.get("exp")
    return not (isinstance(exp, (int, float)) and int(exp) < now)


class IdpAcrHitlStepUpProvider:
    """Verify IdP-issued step-up JWTs bound to subject + card_id via ACR/AMR policy.

    ``webauthn`` method is the same JWT path with an AMR gate (IdP performed WebAuthn);
    the API does not embed authenticator crypto — that lives at the IdP.
    """

    def __init__(
        self,
        *,
        method: Literal["idp_acr", "webauthn"],
        decode_claims: ClaimsDecoder,
        required_acr: frozenset[str] | tuple[str, ...] | str,
        required_amr: frozenset[str] | tuple[str, ...] | str = (),
        card_claim: str = "hitl_card_id",
        max_age_seconds: int = 300,
        authorize_url_template: str = "",
    ) -> None:
        if method not in {"idp_acr", "webauthn"}:
            raise ValueError(f"unsupported IdP step-up method: {method}")
        acr = _as_str_set(required_acr)
        if not acr:
            raise ValueError("HITL_STEP_UP_REQUIRED_ACR must list at least one ACR value")
        amr = _as_str_set(required_amr)
        if method == "webauthn" and not amr:
            amr = frozenset({"webauthn"})
        claim = card_claim.strip()
        if not claim:
            raise ValueError("HITL_STEP_UP_CARD_CLAIM must not be empty")
        if max_age_seconds < 30 or max_age_seconds > 3600:
            raise ValueError("HITL_STEP_UP_MAX_AGE_SECONDS must be 30..3600")
        self._method: HitlStepUpMethod = method
        self._decode = decode_claims
        self._required_acr = acr
        self._required_amr = amr
        self._card_claim = claim
        self._max_age = max_age_seconds
        self._authorize_template = authorize_url_template.strip()

    @property
    def method(self) -> HitlStepUpMethod:
        """Configured ceremony method."""
        return self._method

    def issue_challenge(self, *, card_id: str, subject: str) -> HitlStepUpChallenge:
        """Return IdP ceremony metadata; client obtains JWT from IdP (assertion left null)."""
        nonce = secrets.token_urlsafe(24)
        primary_acr = sorted(self._required_acr)[0]
        authorize_url = render_step_up_authorize_url(
            self._authorize_template,
            card_id=card_id,
            subject=subject,
            challenge=nonce,
            required_acr=primary_acr,
            card_claim=self._card_claim,
            method=self._method,
        )
        return HitlStepUpChallenge(
            required=True,
            method=self._method,
            assertion=None,
            challenge=nonce,
            required_acr=primary_acr,
            required_amr=tuple(sorted(self._required_amr)),
            card_claim=self._card_claim,
            authorize_url=authorize_url,
            card_id=card_id,
        )

    def verify(self, *, card_id: str, subject: str, assertion: str) -> bool:
        """Return True when JWT proves elevated ACR/AMR for this card+subject."""
        token = assertion.strip()
        if not token or not card_id or not subject.strip():
            return False
        try:
            claims = dict(self._decode(token))
        except jwt.PyJWTError, ValueError, TypeError, KeyError:
            return False

        sub = claims.get("sub")
        if not isinstance(sub, str) or sub.strip() != subject.strip():
            return False

        bound = claims.get(self._card_claim)
        if not isinstance(bound, str) or bound.strip() != card_id:
            return False

        if not _acr_matches(claims.get("acr"), self._required_acr):
            return False

        if self._required_amr and not (_as_str_set(claims.get("amr")) & self._required_amr):
            return False

        return _fresh_enough(claims, now=int(time.time()), max_age=self._max_age)

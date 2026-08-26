# tests/unit/test_hitl_idp_step_up.py

"""IdP ACR / WebAuthn-backed HITL step-up provider (contract, not phrase hardcodes)."""

from __future__ import annotations

import time

import jwt
import pytest

from palatium_ai.infrastructure.hitl.idp_acr_step_up import IdpAcrHitlStepUpProvider

_TEST_HS_KEY = "unit-test-hs-key-16"  # noqa: S105


def _mint(
    *,
    secret: str,
    sub: str,
    card_id: str,
    acr: str = "urn:palatium:acr:step-up",
    amr: list[str] | None = None,
    iat_offset: int = 0,
    exp_offset: int = 300,
) -> str:
    now = int(time.time()) + iat_offset
    payload: dict[str, object] = {
        "sub": sub,
        "iat": now,
        "exp": now + exp_offset,
        "acr": acr,
        "hitl_card_id": card_id,
    }
    if amr is not None:
        payload["amr"] = amr
    return jwt.encode(payload, secret, algorithm="HS256")


def test_idp_acr_challenge_has_no_preminted_assertion() -> None:
    provider = IdpAcrHitlStepUpProvider(
        method="idp_acr",
        decode_claims=lambda token: jwt.decode(token, _TEST_HS_KEY, algorithms=["HS256"]),
        required_acr="urn:palatium:acr:step-up",
        authorize_url_template="https://idp.example/authorize?c={card_id}&n={challenge}&acr={required_acr}",
    )
    challenge = provider.issue_challenge(card_id="card-1", subject="user-a")
    assert challenge.required is True
    assert challenge.method == "idp_acr"
    assert challenge.assertion is None
    assert challenge.challenge
    assert challenge.card_claim == "hitl_card_id"
    assert challenge.required_acr == "urn:palatium:acr:step-up"
    assert challenge.authorize_url is not None
    assert "card-1" in challenge.authorize_url
    assert challenge.challenge in challenge.authorize_url


def test_idp_acr_verify_accepts_bound_token() -> None:
    provider = IdpAcrHitlStepUpProvider(
        method="idp_acr",
        decode_claims=lambda token: jwt.decode(token, _TEST_HS_KEY, algorithms=["HS256"]),
        required_acr={"urn:palatium:acr:step-up"},
    )
    token = _mint(secret=_TEST_HS_KEY, sub="user-a", card_id="card-9")
    assert provider.verify(card_id="card-9", subject="user-a", assertion=token) is True


@pytest.mark.parametrize(
    ("kwargs",),
    [
        ({"sub": "other"},),
        ({"card_id": "wrong-card"},),
        ({"acr": "urn:other"},),
        ({"iat_offset": -400, "exp_offset": 10},),
    ],
)
def test_idp_acr_verify_rejects_broken_binding(kwargs: dict[str, object]) -> None:
    provider = IdpAcrHitlStepUpProvider(
        method="idp_acr",
        decode_claims=lambda token: jwt.decode(token, _TEST_HS_KEY, algorithms=["HS256"]),
        required_acr="urn:palatium:acr:step-up",
        max_age_seconds=300,
    )
    base: dict[str, object] = {"secret": _TEST_HS_KEY, "sub": "user-a", "card_id": "card-9"}
    base.update(kwargs)
    token = _mint(**base)  # type: ignore[arg-type]
    assert provider.verify(card_id="card-9", subject="user-a", assertion=token) is False


def test_webauthn_method_requires_amr_intersection() -> None:
    provider = IdpAcrHitlStepUpProvider(
        method="webauthn",
        decode_claims=lambda token: jwt.decode(token, _TEST_HS_KEY, algorithms=["HS256"]),
        required_acr="urn:palatium:acr:step-up",
    )
    bare = _mint(secret=_TEST_HS_KEY, sub="user-a", card_id="card-9")
    assert provider.verify(card_id="card-9", subject="user-a", assertion=bare) is False
    with_amr = _mint(secret=_TEST_HS_KEY, sub="user-a", card_id="card-9", amr=["pwd", "webauthn"])
    assert provider.verify(card_id="card-9", subject="user-a", assertion=with_amr) is True
    challenge = provider.issue_challenge(card_id="card-9", subject="user-a")
    assert challenge.method == "webauthn"
    assert "webauthn" in challenge.required_amr

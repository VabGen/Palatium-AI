"""Environment hardening gates for staging/production."""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from palatium_ai.presentation.app import _assert_environment_hardening


def _settings(
    *,
    environment: str = "staging",
    auth_enabled: bool = True,
    turn_budget: float = 1.0,
    daily_budget: float = 10.0,
    default_provider: str = "ollama",
    fallback: str = "openai",
    hitl_step_up_method: str = "idp_acr",
    jwt_algorithm: str = "RS256",
    cors_origin_list: tuple[str, ...] = ("https://app.palatium.example",),
    hitl_signing_secret: object | None = None,
) -> SimpleNamespace:
    llm = SimpleNamespace(
        default_provider=default_provider,
        fallback_providers=fallback,
        build_provider_chain=lambda primary: tuple(
            dict.fromkeys(
                [
                    primary,
                    *[
                        name.strip().lower()
                        for name in fallback.split(",")
                        if name.strip() and name.strip().lower() != primary
                    ],
                ]
            )
        ),
    )
    return SimpleNamespace(
        app=SimpleNamespace(environment=environment),
        security=SimpleNamespace(
            auth_enabled=auth_enabled,
            hitl_step_up_method=hitl_step_up_method,
            jwt_algorithm=jwt_algorithm,
            cors_origin_list=cors_origin_list,
            hitl_signing_secret=hitl_signing_secret,
        ),
        observability=SimpleNamespace(
            turn_cost_budget_usd=turn_budget,
            daily_cost_budget_usd=daily_budget,
        ),
        llm=llm,
    )


def test_hardening_skipped_in_development() -> None:
    _assert_environment_hardening(
        _settings(environment="development", auth_enabled=False, turn_budget=0, daily_budget=0, fallback="")
    )


def test_hardening_requires_auth_budgets_and_fallback() -> None:
    with pytest.raises(RuntimeError, match="AUTH_ENABLED"):
        _assert_environment_hardening(_settings(auth_enabled=False))
    with pytest.raises(RuntimeError, match="TURN_COST_BUDGET"):
        _assert_environment_hardening(_settings(turn_budget=0))
    with pytest.raises(RuntimeError, match="DAILY_COST_BUDGET"):
        _assert_environment_hardening(_settings(daily_budget=0))
    with pytest.raises(RuntimeError, match="LLM_FALLBACK"):
        _assert_environment_hardening(_settings(fallback=""))
    with pytest.raises(RuntimeError, match="HITL_STEP_UP_METHOD"):
        _assert_environment_hardening(_settings(hitl_step_up_method="hmac_stub"))
    _assert_environment_hardening(_settings())
    _assert_environment_hardening(_settings(hitl_step_up_method="webauthn"))


def test_hardening_rejects_symmetric_jwt_in_production() -> None:
    with pytest.raises(RuntimeError, match="JWT_ALGORITHM"):
        _assert_environment_hardening(_settings(jwt_algorithm="HS256"))


def test_hardening_rejects_loopback_cors_in_production() -> None:
    with pytest.raises(RuntimeError, match="loopback"):
        _assert_environment_hardening(_settings(cors_origin_list=("http://localhost:8000",)))
    with pytest.raises(RuntimeError, match="loopback"):
        _assert_environment_hardening(_settings(cors_origin_list=("https://app.example", "http://127.0.0.1:8000")))


def test_hardening_rejects_short_hitl_signing_secret() -> None:
    short_secret = SimpleNamespace(get_secret_value=lambda: "too-short")
    with pytest.raises(RuntimeError, match="HITL_SIGNING_SECRET"):
        _assert_environment_hardening(_settings(hitl_signing_secret=short_secret))


def test_hardening_accepts_asymmetric_jwt_and_public_cors() -> None:
    long_secret = SimpleNamespace(get_secret_value=lambda: "x" * 48)
    _assert_environment_hardening(
        _settings(
            jwt_algorithm="ES256", cors_origin_list=("https://app.palatium.example",), hitl_signing_secret=long_secret
        )
    )

# src/palatium_ai/infrastructure/hitl/step_up_jwt.py

"""Decode step-up JWTs with the same material as API auth (HS* / JWKS)."""

from __future__ import annotations

from typing import Any

import jwt

from jwt import PyJWKClient

from palatium_ai.core.config.security import SecurityConfig


class StepUpJwtDecoder:
    """Verify and return claims for HITL IdP/WebAuthn step-up assertions."""

    def __init__(self, security: SecurityConfig) -> None:
        self._security = security
        self._jwks_client: PyJWKClient | None = None
        if security.jwks_url is not None and (
            security.jwt_algorithm.startswith("RS") or security.jwt_algorithm.startswith("ES")
        ):
            self._jwks_client = PyJWKClient(str(security.jwks_url), cache_keys=True)

    def __call__(self, token: str) -> dict[str, Any]:
        """Decode a bearer JWT; raise jwt.PyJWTError on failure."""
        options = {"require": ["exp", "sub", "iat"]}
        decode_kwargs: dict[str, Any] = {
            "algorithms": [self._security.jwt_algorithm],
            "options": options,
        }
        if self._security.jwt_audience:
            decode_kwargs["audience"] = self._security.jwt_audience
        if self._security.jwt_issuer:
            decode_kwargs["issuer"] = self._security.jwt_issuer

        if self._security.jwt_algorithm.startswith("HS"):
            if self._security.jwt_secret is None:
                raise jwt.InvalidTokenError("JWT_SECRET is not configured")
            return jwt.decode(
                token,
                self._security.jwt_secret.get_secret_value(),
                **decode_kwargs,
            )

        if self._jwks_client is None:
            raise jwt.InvalidTokenError("JWKS client is not configured for step-up")
        signing_key = self._jwks_client.get_signing_key_from_jwt(token)
        return jwt.decode(token, signing_key.key, **decode_kwargs)

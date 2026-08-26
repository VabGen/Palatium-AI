# src/palatium_ai/presentation/security/jwt.py

"""JWT verification (HS* local secret / RS*|ES* via JWKS)."""

from __future__ import annotations

import time

from typing import Any

import httpx
import jwt

from jwt import PyJWKClient

from palatium_ai.core.config.security import SecurityConfig
from palatium_ai.presentation.security.principal import AuthPrincipal


class JwtValidationError(Exception):
    """Raised when a bearer token cannot be verified."""


class JwtTokenService:
    """Issue (dev) and verify access tokens according to SecurityConfig."""

    def __init__(self, security: SecurityConfig) -> None:
        self._security = security
        self._jwks_client: PyJWKClient | None = None
        if security.jwks_url is not None and (
            security.jwt_algorithm.startswith("RS") or security.jwt_algorithm.startswith("ES")
        ):
            self._jwks_client = PyJWKClient(str(security.jwks_url), cache_keys=True)

    def issue_dev_token(
        self,
        *,
        subject: str,
        org_id: str | None = None,
        roles: tuple[str, ...] = (),
        ttl_seconds: int | None = None,
    ) -> tuple[str, int]:
        """Mint a short-lived HS* token for local UI (development only)."""
        if not self._security.jwt_algorithm.startswith("HS"):
            raise JwtValidationError("Dev tokens require HS* JWT_ALGORITHM")
        if self._security.jwt_secret is None:
            raise JwtValidationError("JWT_SECRET is not configured")
        ttl = ttl_seconds if ttl_seconds is not None else self._security.jwt_dev_token_ttl_seconds
        now = int(time.time())
        payload: dict[str, Any] = {
            "sub": subject,
            "iat": now,
            "exp": now + ttl,
            "roles": list(roles),
        }
        if org_id:
            payload["org_id"] = org_id
        if self._security.jwt_issuer:
            payload["iss"] = self._security.jwt_issuer
        if self._security.jwt_audience:
            payload["aud"] = self._security.jwt_audience
        token = jwt.encode(
            payload,
            self._security.jwt_secret.get_secret_value(),
            algorithm=self._security.jwt_algorithm,
        )
        return token, ttl

    def verify_bearer(self, token: str) -> AuthPrincipal:
        """Verify bearer JWT and map claims to AuthPrincipal."""
        try:
            claims = self._decode(token)
        except jwt.PyJWTError as exc:
            raise JwtValidationError(str(exc)) from exc
        subject = claims.get("sub")
        if not isinstance(subject, str) or not subject.strip():
            raise JwtValidationError("JWT missing subject (sub)")
        roles = _extract_roles(claims)
        org_raw = claims.get("org_id") or claims.get("org")
        org_id = org_raw if isinstance(org_raw, str) and org_raw.strip() else None
        jti = claims.get("jti")
        token_id = jti if isinstance(jti, str) else None
        return AuthPrincipal(
            subject=subject.strip(),
            roles=roles,
            org_id=org_id,
            token_id=token_id,
        )

    def _decode(self, token: str) -> dict[str, Any]:
        options = {"require": ["exp", "sub"]}
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
                raise JwtValidationError("JWT_SECRET is not configured")
            return jwt.decode(
                token,
                self._security.jwt_secret.get_secret_value(),
                **decode_kwargs,
            )

        if self._jwks_client is None:
            raise JwtValidationError("JWKS client is not configured")
        signing_key = self._jwks_client.get_signing_key_from_jwt(token)
        return jwt.decode(token, signing_key.key, **decode_kwargs)


def _extract_roles(claims: dict[str, Any]) -> frozenset[str]:
    raw = claims.get("roles")
    if raw is None:
        raw = claims.get("role")
    if isinstance(raw, str):
        return frozenset(part.strip() for part in raw.split(",") if part.strip())
    if isinstance(raw, (list, tuple, set)):
        return frozenset(str(item).strip() for item in raw if str(item).strip())
    realm = claims.get("realm_access")
    if isinstance(realm, dict):
        realm_roles = realm.get("roles")
        if isinstance(realm_roles, list):
            return frozenset(str(item).strip() for item in realm_roles if str(item).strip())
    return frozenset()


def probe_jwks_reachable(url: str, *, timeout_seconds: float = 2.0) -> bool:
    """Best-effort connectivity check used only in diagnostics (not startup-critical)."""
    try:
        response = httpx.get(url, timeout=timeout_seconds)
        return response.status_code < 500
    except httpx.HTTPError:
        return False

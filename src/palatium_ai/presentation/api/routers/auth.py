# src/palatium_ai/presentation/api/routers/auth.py

"""Auth helpers — development token mint + local IdP step-up stub."""

from __future__ import annotations

import html
import time

from typing import Any
from urllib.parse import urlparse

import jwt

from fastapi import APIRouter, HTTPException, Query, Request, status
from fastapi.responses import HTMLResponse, JSONResponse
from pydantic import BaseModel, Field

from palatium_ai.presentation.security.jwt import JwtTokenService, JwtValidationError

router = APIRouter()


class DevTokenRequest(BaseModel):
    """Local UI bootstrap identity (development environment only)."""

    user_id: str = Field(min_length=1, max_length=128)
    org_id: str | None = Field(default=None, max_length=128)
    roles: tuple[str, ...] = Field(default_factory=tuple, max_length=16)


class DevTokenResponse(BaseModel):
    """Bearer access token for local chat shell."""

    access_token: str
    token_type: str = "bearer"  # noqa: S105 — OAuth token_type literal, not a secret
    expires_in: int


class DevHitlStepUpAssertion(BaseModel):
    """Minted step-up JWT for local IdP stub."""

    assertion: str
    card_id: str
    method: str


@router.post("/dev-token", response_model=DevTokenResponse)
async def issue_dev_token(body: DevTokenRequest, request: Request) -> DevTokenResponse:
    """Mint HS* JWT for local UI. Disabled outside `development`."""
    settings = request.app.state.settings
    if settings.app.environment != "development":
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Dev token endpoint is only available in development",
        )
    tokens: JwtTokenService = request.app.state.token_service
    admin_roles = settings.security.admin_role_set
    manager_roles = settings.security.manager_role_set
    privileged = admin_roles | manager_roles
    safe_roles = tuple(role for role in body.roles if role.strip() not in privileged)
    try:
        token, ttl = tokens.issue_dev_token(
            subject=body.user_id,
            org_id=body.org_id,
            roles=safe_roles,
        )
    except JwtValidationError as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=str(exc),
        ) from exc
    return DevTokenResponse(access_token=token, expires_in=ttl)


@router.get("/dev-hitl-step-up", response_model=None)
async def issue_dev_hitl_step_up(
    request: Request,
    card_id: str = Query(min_length=1, max_length=64),
    subject: str = Query(min_length=1, max_length=128),
    challenge: str = Query(default="", max_length=512),
    required_acr: str = Query(default="urn:palatium:acr:step-up", max_length=256),
    card_claim: str = Query(default="hitl_card_id", max_length=64),
    method: str = Query(default="idp_acr", max_length=32),
    return_origin: str | None = Query(default=None, max_length=512),
) -> HTMLResponse | JSONResponse:
    """Local IdP stand-in: mint bound step-up JWT (HTML postMessage or JSON).

    Disabled outside ``development``. Production must use a real IdP authorize URL.
    """
    _ = challenge
    settings = request.app.state.settings
    if settings.app.environment != "development":
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Dev HITL step-up stub is only available in development",
        )
    if settings.security.jwt_secret is None:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="JWT_SECRET required to mint dev step-up assertions",
        )
    if not settings.security.jwt_algorithm.startswith("HS"):
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Dev HITL step-up stub requires HS* JWT_ALGORITHM",
        )

    now = int(time.time())
    claims: dict[str, Any] = {
        "sub": subject.strip(),
        "iat": now,
        "exp": now + min(300, settings.security.hitl_step_up_max_age_seconds),
        "acr": required_acr.strip() or "urn:palatium:acr:step-up",
        card_claim.strip() or "hitl_card_id": card_id.strip(),
    }
    if method.strip().lower() == "webauthn":
        claims["amr"] = ["webauthn"]
    if settings.security.jwt_issuer:
        claims["iss"] = settings.security.jwt_issuer
    if settings.security.jwt_audience:
        claims["aud"] = settings.security.jwt_audience

    assertion = jwt.encode(
        claims,
        settings.security.jwt_secret.get_secret_value(),
        algorithm=settings.security.jwt_algorithm,
    )
    accept = (request.headers.get("accept") or "").lower()
    if "application/json" in accept:
        return JSONResponse(
            DevHitlStepUpAssertion(
                assertion=assertion,
                card_id=card_id,
                method=method,
            ).model_dump()
        )

    target_origin = _safe_return_origin(return_origin)
    safe_assertion = html.escape(assertion, quote=True)
    safe_origin = html.escape(target_origin or "", quote=True)
    page = f"""<!doctype html>
<html lang="en"><head><meta charset="utf-8"/><title>Dev HITL step-up</title></head>
<body>
<p>Dev IdP stub — posting step-up assertion to opener…</p>
<script>
(function () {{
  var assertion = "{safe_assertion}";
  var target = "{safe_origin}";
  var payload = {{ type: "palatium.hitl.step_up", assertion: assertion }};
  if (window.opener && target) {{
    window.opener.postMessage(payload, target);
  }}
  document.body.insertAdjacentHTML("beforeend", "<p>Done. You can close this window.</p>");
}})();
</script>
</body></html>
"""
    return HTMLResponse(content=page)


def _safe_return_origin(value: str | None) -> str | None:
    if value is None or not value.strip():
        return None
    cleaned = value.strip()
    parsed = urlparse(cleaned)
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        return None
    if parsed.path not in {"", "/"} or parsed.query or parsed.fragment:
        # Origin must be scheme://host[:port] only.
        return f"{parsed.scheme}://{parsed.netloc}"
    return cleaned

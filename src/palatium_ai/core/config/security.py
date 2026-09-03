# src/palatium_ai/core/config/security.py

"""Настройки Zero Trust: JWT, CORS, rate limit."""

from __future__ import annotations

from pydantic import Field, HttpUrl, SecretStr, field_validator

from .base import BaseConfig


class SecurityConfig(BaseConfig):
    """Настройки безопасности API Gateway-слоя."""

    auth_enabled: bool = Field(default=True, validation_alias="AUTH_ENABLED")
    jwt_algorithm: str = Field(default="HS256", validation_alias="JWT_ALGORITHM")
    jwt_secret: SecretStr | None = Field(default=None, validation_alias="JWT_SECRET")
    jwks_url: HttpUrl | None = Field(default=None, validation_alias="JWKS_URL")
    jwt_issuer: str | None = Field(default=None, validation_alias="JWT_ISSUER")
    jwt_audience: str | None = Field(default=None, validation_alias="JWT_AUDIENCE")
    jwt_dev_token_ttl_seconds: int = Field(
        default=12 * 60 * 60,
        ge=300,
        le=7 * 24 * 60 * 60,
        validation_alias="JWT_DEV_TOKEN_TTL_SECONDS",
    )
    cors_origins: str = Field(
        default="http://127.0.0.1:8000,http://localhost:8000",
        validation_alias="CORS_ORIGINS",
    )
    api_rate_limit: int = Field(default=100, ge=1, validation_alias="API_RATE_LIMIT")
    api_rate_limit_window_seconds: int = Field(
        default=60,
        ge=1,
        le=3600,
        validation_alias="API_RATE_LIMIT_WINDOW_SECONDS",
    )
    api_rate_limit_path_prefixes: str = Field(
        default=("/api/intents/,/api/hitl/,/api/documents/,/api/sessions/,/api/admin/,/api/agents/,/api/memory/"),
        validation_alias="API_RATE_LIMIT_PATH_PREFIXES",
        description="Comma-separated path prefixes protected by the API rate limiter.",
    )
    admin_roles: str = Field(default="admin", validation_alias="ADMIN_ROLES")
    manager_roles: str = Field(
        default="manager,admin",
        validation_alias="MANAGER_ROLES",
        description="Roles that receive HITL timeout escalations (risk_score > 0.5).",
    )
    metrics_public: bool = Field(
        default=True,
        validation_alias="METRICS_PUBLIC",
        description="When false, GET /metrics requires a verified JWT (admin scrape token).",
    )
    hitl_signing_secret: SecretStr | None = Field(
        default=None,
        validation_alias="HITL_SIGNING_SECRET",
        description="HMAC key for HITL action tokens; falls back to JWT_SECRET when unset.",
    )
    hitl_step_up_method: str = Field(
        default="hmac_stub",
        validation_alias="HITL_STEP_UP_METHOD",
        description="hmac_stub (local) | idp_acr | webauthn (IdP JWT with AMR gate).",
    )
    hitl_step_up_required_acr: str = Field(
        default="urn:palatium:acr:step-up",
        validation_alias="HITL_STEP_UP_REQUIRED_ACR",
        description="Comma-separated ACR values accepted for IdP/WebAuthn step-up JWTs.",
    )
    hitl_step_up_required_amr: str = Field(
        default="",
        validation_alias="HITL_STEP_UP_REQUIRED_AMR",
        description="Comma-separated AMR values; webauthn method defaults to webauthn when empty.",
    )
    hitl_step_up_card_claim: str = Field(
        default="hitl_card_id",
        validation_alias="HITL_STEP_UP_CARD_CLAIM",
        description="JWT claim that must equal the HITL card_id (binding).",
    )
    hitl_step_up_max_age_seconds: int = Field(
        default=300,
        ge=30,
        le=3600,
        validation_alias="HITL_STEP_UP_MAX_AGE_SECONDS",
    )
    hitl_step_up_authorize_url: str = Field(
        default="",
        validation_alias="HITL_STEP_UP_AUTHORIZE_URL",
        description=(
            "Optional http(s) template for IdP/WebAuthn start. Placeholders: "
            "{card_id},{subject},{challenge},{required_acr},{card_claim},{method}."
        ),
    )
    hitl_step_up_required: bool | None = Field(
        default=None,
        validation_alias="HITL_STEP_UP_REQUIRED",
        description="Override step-up enforcement; None → enforce only in staging/production.",
    )
    hitl_notify_webhook_url: HttpUrl | None = Field(
        default=None,
        validation_alias="HITL_NOTIFY_WEBHOOK_URL",
        description="Optional HTTPS webhook for HITL timeout escalations (OOB manager notify).",
    )
    hitl_notify_webhook_timeout_seconds: float = Field(
        default=5.0,
        ge=0.5,
        le=30.0,
        validation_alias="HITL_NOTIFY_WEBHOOK_TIMEOUT_SECONDS",
    )
    hitl_notify_email_to: str = Field(
        default="",
        validation_alias="HITL_NOTIFY_EMAIL_TO",
        description="Comma-separated escalation recipients; empty disables email channel.",
    )
    hitl_notify_email_from: str = Field(
        default="",
        validation_alias="HITL_NOTIFY_EMAIL_FROM",
    )
    hitl_notify_smtp_host: str = Field(default="", validation_alias="HITL_NOTIFY_SMTP_HOST")
    hitl_notify_smtp_port: int = Field(
        default=587,
        ge=1,
        le=65535,
        validation_alias="HITL_NOTIFY_SMTP_PORT",
    )
    hitl_notify_smtp_username: str = Field(default="", validation_alias="HITL_NOTIFY_SMTP_USERNAME")
    hitl_notify_smtp_password: SecretStr | None = Field(
        default=None,
        validation_alias="HITL_NOTIFY_SMTP_PASSWORD",
    )
    hitl_notify_smtp_use_tls: bool = Field(default=True, validation_alias="HITL_NOTIFY_SMTP_USE_TLS")
    hitl_notify_slack_bot_token: SecretStr | None = Field(
        default=None,
        validation_alias="HITL_NOTIFY_SLACK_BOT_TOKEN",
    )
    hitl_notify_slack_channel: str = Field(
        default="",
        validation_alias="HITL_NOTIFY_SLACK_CHANNEL",
        description="Slack channel id or name for chat.postMessage.",
    )

    @field_validator("jwt_algorithm")
    @classmethod
    def _normalize_algorithm(cls, value: str) -> str:
        normalized = value.strip().upper()
        if not normalized:
            raise ValueError("JWT_ALGORITHM must not be empty")
        return normalized

    @field_validator("hitl_step_up_method")
    @classmethod
    def _normalize_step_up_method(cls, value: str) -> str:
        normalized = value.strip().lower()
        allowed = {"hmac_stub", "idp_acr", "webauthn"}
        if normalized not in allowed:
            raise ValueError(f"HITL_STEP_UP_METHOD must be one of {sorted(allowed)}")
        return normalized

    @field_validator("jwks_url", "hitl_notify_webhook_url", mode="before")
    @classmethod
    def _empty_jwks_to_none(cls, value: object) -> object:
        if value is None or value == "":
            return None
        return value

    @field_validator(
        "jwt_secret",
        "hitl_signing_secret",
        "hitl_notify_smtp_password",
        "hitl_notify_slack_bot_token",
        mode="before",
    )
    @classmethod
    def _empty_secret_to_none(cls, value: object) -> object:
        if value is None or value == "":
            return None
        return value

    @field_validator("jwt_issuer", "jwt_audience", mode="before")
    @classmethod
    def _empty_str_to_none(cls, value: object) -> object:
        if value is None or value == "":
            return None
        return value

    @field_validator("hitl_step_up_required", mode="before")
    @classmethod
    def _empty_bool_override_to_none(cls, value: object) -> object:
        if value is None or value == "":
            return None
        return value

    @field_validator("cors_origins")
    @classmethod
    def _forbid_cors_wildcards(cls, value: str) -> str:
        origins = tuple(origin.strip() for origin in value.split(",") if origin.strip())
        if not origins:
            raise ValueError("CORS_ORIGINS must list at least one origin")
        for origin in origins:
            if origin == "*" or "*" in origin:
                raise ValueError("CORS_ORIGINS must not contain wildcards (*)")
        return value

    @property
    def cors_origin_list(self) -> tuple[str, ...]:
        """Parsed CORS allow-list (wildcards rejected at validation)."""
        return tuple(origin.strip() for origin in self.cors_origins.split(",") if origin.strip())

    @property
    def rate_limit_path_prefixes(self) -> tuple[str, ...]:
        """Path prefixes subject to API_RATE_LIMIT."""
        prefixes = tuple(prefix.strip() for prefix in self.api_rate_limit_path_prefixes.split(",") if prefix.strip())
        if not prefixes:
            raise RuntimeError("API_RATE_LIMIT_PATH_PREFIXES must list at least one prefix")
        return prefixes

    @property
    def admin_role_set(self) -> frozenset[str]:
        """Role names that grant admin API access (e.g. list all sessions)."""
        return frozenset(role.strip() for role in self.admin_roles.split(",") if role.strip())

    @property
    def manager_role_set(self) -> frozenset[str]:
        """Roles for HITL high-risk timeout escalation queue."""
        return frozenset(role.strip() for role in self.manager_roles.split(",") if role.strip())

    @property
    def hitl_step_up_acr_set(self) -> frozenset[str]:
        """Accepted ACR values for IdP step-up JWTs."""
        return frozenset(
            part.strip() for part in self.hitl_step_up_required_acr.replace(" ", ",").split(",") if part.strip()
        )

    @property
    def hitl_step_up_amr_set(self) -> frozenset[str]:
        """Accepted AMR values for IdP/WebAuthn step-up JWTs."""
        return frozenset(
            part.strip() for part in self.hitl_step_up_required_amr.replace(" ", ",").split(",") if part.strip()
        )

    @property
    def hitl_notify_email_recipients(self) -> tuple[str, ...]:
        """Parsed HITL_NOTIFY_EMAIL_TO list."""
        return tuple(part.strip() for part in self.hitl_notify_email_to.split(",") if part.strip())

    def effective_hitl_step_up_required(self, environment: str) -> bool:
        """Whether high-risk MCP approve requires step-up for this deployment."""
        if self.hitl_step_up_required is not None:
            return self.hitl_step_up_required
        return environment in {"staging", "production"}

    def optional_hitl_hmac_secret(self) -> str | None:
        """HITL HMAC secret when configured (HITL_SIGNING_SECRET or JWT_SECRET)."""
        if self.hitl_signing_secret is not None:
            value = self.hitl_signing_secret.get_secret_value().strip()
            return value or None
        if self.jwt_secret is not None:
            value = self.jwt_secret.get_secret_value().strip()
            return value or None
        return None

    def hitl_hmac_secret(self) -> str:
        """Secret used to mint/verify HITL action tokens (required when auth is on)."""
        secret = self.optional_hitl_hmac_secret()
        if secret:
            return secret
        raise RuntimeError("HITL action tokens require HITL_SIGNING_SECRET or JWT_SECRET")

    def require_auth_material(self) -> None:
        """Fail fast when AUTH_ENABLED but signing/verification material is missing."""
        if not self.auth_enabled:
            return
        if self.jwt_algorithm.startswith("HS"):
            secret = self.jwt_secret.get_secret_value() if self.jwt_secret is not None else ""
            if not secret:
                raise RuntimeError("AUTH_ENABLED requires JWT_SECRET when JWT_ALGORITHM is HS* (local/dev)")
        elif self.jwt_algorithm.startswith("RS") or self.jwt_algorithm.startswith("ES"):
            if self.jwks_url is None:
                raise RuntimeError("AUTH_ENABLED requires JWKS_URL when JWT_ALGORITHM is RS*/ES* (staging/prod)")
            if self.hitl_signing_secret is None:
                raise RuntimeError("AUTH_ENABLED with RS*/ES* requires HITL_SIGNING_SECRET for HITL action tokens")
        else:
            raise RuntimeError(f"Unsupported JWT_ALGORITHM: {self.jwt_algorithm}")
        _ = self.hitl_hmac_secret()

# src/palatium_ai/core/config/mcp.py

"""Модуль MCP (Model Context Protocol) содержит класс MCPConfig."""

from __future__ import annotations

from pydantic import Field, SecretStr, field_validator

from .base import BaseConfig


class MCPConfig(BaseConfig):
    """Конфигурация MCP-серверов."""

    enabled: bool = Field(default=True, validation_alias="MCP_ENABLED")
    servers: dict[str, str] = Field(default={}, validation_alias="MCP_SERVERS")
    servers_file: str | None = Field(default=None, validation_alias="MCP_SERVERS_FILE")
    timeout_seconds: int = Field(default=30, validation_alias="MCP_TIMEOUT_SECONDS")
    retry_attempts: int = Field(default=3, validation_alias="MCP_RETRY_ATTEMPTS")
    retry_delay: float = Field(default=1.0, validation_alias="MCP_RETRY_DELAY")
    consul_watch_interval: int = Field(default=60, validation_alias="MCP_CONSUL_WATCH_INTERVAL")

    # Shared Bearer for platform → MCP servers (stubs and real adapters).
    auth_token: SecretStr | None = Field(default=None, validation_alias="MCP_AUTH_TOKEN")
    # Optional per-server overrides: {"edms":"token-a","analytics":"token-b"}
    server_auth_tokens: dict[str, str] = Field(
        default_factory=dict,
        validation_alias="MCP_SERVER_AUTH_TOKENS",
    )
    # When true, startup fails if neither auth_token nor per-server tokens cover servers.
    auth_required: bool = Field(default=False, validation_alias="MCP_AUTH_REQUIRED")
    # Allow http://127.0.0.1|localhost for local stubs (disable in locked-down envs).
    allow_http_loopback: bool = Field(default=True, validation_alias="MCP_ALLOW_HTTP_LOOPBACK")
    # Extra hosts permitted for http:// (Compose DNS names). Comma-separated.
    http_allowed_hosts: str = Field(
        default="localhost,127.0.0.1,::1,mcp-edms,mcp-analytics",
        validation_alias="MCP_HTTP_ALLOWED_HOSTS",
    )

    consul_url: str | None = Field(default=None, validation_alias="MCP_CONSUL_URL")
    consul_token: str | None = Field(default=None, validation_alias="MCP_CONSUL_TOKEN")
    consul_datacenter: str | None = Field(default=None, validation_alias="MCP_CONSUL_DATACENTER")
    consul_prefix: str = Field(default="mcp/", validation_alias="MCP_CONSUL_PREFIX")

    @field_validator("auth_token", mode="before")
    @classmethod
    def _empty_auth_token_as_none(cls, value: object) -> object:
        if value is None or value == "":
            return None
        return value

    def resolve_auth_token(self, server_name: str) -> str | None:
        """Return Bearer token for a server (per-server override, else shared)."""
        override = self.server_auth_tokens.get(server_name)
        if override is not None and override.strip():
            return override.strip()
        if self.auth_token is None:
            return None
        return self.auth_token.get_secret_value()

    def http_host_allowlist(self) -> frozenset[str]:
        """Hosts allowed to use http:// (never https bypass)."""
        return frozenset(part.strip().lower() for part in self.http_allowed_hosts.split(",") if part.strip())

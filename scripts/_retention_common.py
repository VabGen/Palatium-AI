"""Shared helpers for MCP retention maintenance scripts."""

from __future__ import annotations

import os

from datetime import UTC, datetime

from palatium_ai.core.observability.audit import get_audit_logger

RETENTION_CONVERSATION_ID = "admin.retention.mcp_tool_calls"
EXIT_SUCCESS: int = 0
EXIT_INVALID_CONFIG: int = 2
EXIT_RUNTIME_ERROR: int = 3


async def write_retention_audit(event: str, metadata: dict[str, object]) -> None:
    """Append a retention-related audit event with normalized string metadata."""
    normalized = {key: str(value) for key, value in metadata.items()}
    timestamp = datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")
    await get_audit_logger().append_async(
        timestamp=timestamp,
        conversation_id=RETENTION_CONVERSATION_ID,
        event=event,
        metadata=normalized,
    )


def read_int_env(name: str, default: int | None = None) -> int | None:
    """Read an integer environment variable, returning default when missing."""
    raw = os.getenv(name)
    if raw is None or raw == "":
        return default
    return int(raw)


def read_optional_str_env(name: str) -> str | None:
    """Read a string environment variable, treating empty values as None."""
    raw = os.getenv(name)
    if raw is None or raw == "":
        return None
    return raw


def read_optional_bool_env(name: str) -> bool | None:
    """Read a boolean environment variable from true/false/1/0/yes/no values."""
    raw = os.getenv(name)
    if raw is None or raw == "":
        return None
    normalized = raw.strip().lower()
    if normalized in {"1", "true", "yes", "on"}:
        return True
    if normalized in {"0", "false", "no", "off"}:
        return False
    raise ValueError(f"Environment variable {name} must be a boolean-like value")

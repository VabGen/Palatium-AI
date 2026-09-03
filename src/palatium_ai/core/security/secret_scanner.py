# src/palatium_ai/core/security/secret_scanner.py

"""Central secret pattern scanner (020) — before LLM, logging, and audit."""

from __future__ import annotations

import re

_SECRET_VALUE_PATTERNS: tuple[re.Pattern[str], ...] = (
    re.compile(r"(?i)\bsk-[a-z0-9]{16,}\b"),
    re.compile(r"\bAKIA[0-9A-Z]{16}\b"),
    re.compile(r"(?i)\bpassword\s*=\s*\S+"),
    re.compile(r"(?i)\bbearer\s+[a-z0-9\-._~+/]+=*"),
    re.compile(r"-----BEGIN (?:RSA |EC )?PRIVATE KEY-----"),
)


def secret_value_patterns() -> tuple[re.Pattern[str], ...]:
    """Shared patterns for scanner and log redaction."""
    return _SECRET_VALUE_PATTERNS


class SecretScanError(ValueError):
    """Raised when input contains a blocked secret pattern."""


def scan_text(text: str, *, field: str = "input") -> None:
    """Raise SecretScanError if text matches a secret pattern."""
    for pattern in _SECRET_VALUE_PATTERNS:
        if pattern.search(text):
            msg = f"Secret pattern detected in {field}"
            raise SecretScanError(msg)


def scan_text_fields(values: dict[str, str], *, prefix: str = "context") -> None:
    """Scan string dict values (e.g. AgentInput.context or audit metadata)."""
    for key, value in values.items():
        if value:
            scan_text(value, field=f"{prefix}.{key}")


def extract_string_fields(payload: object) -> dict[str, str]:
    """Collect top-level string fields from a pydantic model dump for scanning."""
    if not hasattr(payload, "model_dump"):
        return {}
    raw = payload.model_dump(mode="python")
    if not isinstance(raw, dict):
        return {}
    return {str(k): v for k, v in raw.items() if isinstance(v, str) and v.strip()}

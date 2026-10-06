# src/palatium_ai/core/security/secret_scanner.py

"""Central secret pattern scanner (020) — before LLM, logging, and audit.

Two operations over the same pattern set, chosen by the call site:

* :func:`scan_text` — **fail closed**. For durable writes (memory, knowledge, audit
  metadata) a credential-shaped value must stop the write, not be stored masked.
* :func:`redact_text` — **mask and continue**. For content that merely passes *through*
  the platform (a user instruction, an assembled dialog window, an error string).
  The contract of 020 is that a secret never reaches the model, a log or an audit
  record — not that one matching message must abort the caller's whole turn.
"""

from __future__ import annotations

import re

_REDACTED = "[REDACTED]"

#: ``(rule_id, pattern)`` — rule ids are safe to log, the matched span never is.
_SECRET_RULES: tuple[tuple[str, re.Pattern[str]], ...] = (
    ("openai_key", re.compile(r"(?i)\bsk-[a-z0-9]{16,}\b")),
    ("aws_access_key", re.compile(r"\bAKIA[0-9A-Z]{16}\b")),
    ("password_assignment", re.compile(r"(?i)\bpassword\s*=\s*\S+")),
    ("bearer_token", re.compile(r"(?i)\bbearer\s+[a-z0-9\-._~+/]+=*")),
    ("private_key_block", re.compile(r"-----BEGIN (?:RSA |EC )?PRIVATE KEY-----")),
)

_SECRET_VALUE_PATTERNS: tuple[re.Pattern[str], ...] = tuple(pattern for _, pattern in _SECRET_RULES)


def secret_value_patterns() -> tuple[re.Pattern[str], ...]:
    """Shared patterns for scanner and log redaction."""
    return _SECRET_VALUE_PATTERNS


def redact_text(value: str, *, replacement: str = _REDACTED) -> str:
    """Return ``value`` with every secret-shaped substring replaced (020).

    The replacement must stay a plain literal — callers may be redacting inside
    JSON, where introducing a quote or backslash would corrupt the payload.
    """
    redacted = value
    for pattern in _SECRET_VALUE_PATTERNS:
        redacted = pattern.sub(replacement, redacted)
    return redacted


def secret_pattern_labels(value: str) -> tuple[str, ...]:
    """Rule ids matching ``value``, for diagnostics.

    Only the *rule* names are returned, never the matched span, so the result is
    safe to put in a log or a metric label.
    """
    return tuple(rule_id for rule_id, pattern in _SECRET_RULES if pattern.search(value))


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

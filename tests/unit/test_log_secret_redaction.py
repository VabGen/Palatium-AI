"""Unit tests for structlog secret redaction."""

from __future__ import annotations

from palatium_ai.core.logging.redact import redact_secrets, redact_text


def test_redact_secrets_masks_sensitive_keys() -> None:
    event = redact_secrets(
        None,  # type: ignore[arg-type]
        "info",
        {
            "event": "ok",
            "api_key": "sk-abcdefghijklmnopqrstuvwxyz",
            "nested": {"password": "hunter2", "query": "docs"},
        },
    )
    assert event["event"] == "ok"
    assert event["api_key"] == "[REDACTED]"
    nested = event["nested"]
    assert isinstance(nested, dict)
    assert nested["password"] == "[REDACTED]"
    assert nested["query"] == "docs"


def test_redact_text_masks_secret_shaped_substrings() -> None:
    raw = "failed with Authorization: Bearer abcdefghijklmnopqrstuvwxyz012345 and password=leak"
    redacted = redact_text(raw)
    assert "Bearer abcdef" not in redacted
    assert "password=leak" not in redacted
    assert "[REDACTED]" in redacted

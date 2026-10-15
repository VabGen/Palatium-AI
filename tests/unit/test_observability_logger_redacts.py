"""Structlog processor redacts string values before render."""

from __future__ import annotations

from palatium_ai.core.logging.processors import redact_observability_strings


def test_logger_processor_redacts_token_in_kwarg() -> None:
    event = {
        "event": "x",
        "note": "sk-abc123456789012345",
        "count": 1,
    }
    out = redact_observability_strings(None, "info", event)  # type: ignore[arg-type]
    assert out["note"] == "<token>"
    assert out["count"] == 1
    assert "sk-" not in str(out)

"""API redaction for MCP tool-call payloads."""

from __future__ import annotations

from palatium_ai.domain.mcp.api_redaction import redact_mcp_arguments, redact_mcp_content
from palatium_ai.domain.memory.tool_output import contains_untrusted_tool_output, wrap_untrusted_tool_output
from palatium_ai.domain.sessions.ownership import evaluate_session_access


def test_redact_mcp_arguments_strips_secrets_and_truncates() -> None:
    redacted = redact_mcp_arguments(
        {
            "query": "договор",
            "api_key": "sk-should-not-leak",
            "nested": {"access_token": "tok", "note": "x" * 400},
        }
    )
    assert redacted["query"] == "договор"
    assert redacted["api_key"] == "[REDACTED]"
    assert redacted["nested"]["access_token"] == "[REDACTED]"  # noqa: S105
    assert isinstance(redacted["nested"]["note"], str)
    assert redacted["nested"]["note"].endswith("…[truncated]")
    assert "sk-should-not-leak" not in str(redacted)


def test_redact_mcp_content_truncates_text_blocks() -> None:
    content = [{"type": "text", "text": "A" * 2000, "token": "secret-value"}]
    out = redact_mcp_content(content)
    assert len(out) == 1
    assert out[0]["type"] == "text"
    assert out[0]["text"].endswith("…[truncated]")
    assert len(out[0]["text"]) < 600
    assert out[0]["token"] == "[REDACTED]"  # noqa: S105


def test_unowned_session_not_claimable() -> None:
    denied = evaluate_session_access(
        owner_user_id=None,
        caller_user_id="user-a",
        session_exists=True,
        allow_claim=False,
    )
    assert not denied.allowed
    assert denied.reason == "unowned_not_readable"

    still_denied = evaluate_session_access(
        owner_user_id=None,
        caller_user_id="user-a",
        session_exists=True,
        allow_claim=True,
    )
    assert not still_denied.allowed
    assert still_denied.reason == "unowned_not_readable"


def test_contains_untrusted_tool_output_detects_fence() -> None:
    fenced = wrap_untrusted_tool_output('{"ok": true}', source="mcp:edms.search_documents")
    assert contains_untrusted_tool_output(fenced)
    assert not contains_untrusted_tool_output("plain worker draft")

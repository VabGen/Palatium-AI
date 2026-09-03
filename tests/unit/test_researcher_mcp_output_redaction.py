"""Wave 8: MCP tool output is redacted before untrusted fencing (070/020)."""

from __future__ import annotations

from palatium_ai.application.agents.researcher import summarize_mcp_content
from palatium_ai.application.tools.mcp import MCPToolCallOutcome


def test_summarize_mcp_content_redacts_secret_before_fence() -> None:
    secret = "sk-abcdefghijklmnopqrstuvwxyz1234567890"
    outcome = MCPToolCallOutcome(
        content=[{"type": "text", "text": f'{{"token":"{secret}"}}'}],
        is_error=False,
    )
    summary = summarize_mcp_content(
        outcome,
        max_chars=4000,
        server_name="edms",
        tool_name="search_documents",
    )
    assert secret not in summary
    assert "[REDACTED]" in summary
    assert "UNTRUSTED_TOOL_OUTPUT" in summary
    assert "mcp:edms.search_documents" in summary

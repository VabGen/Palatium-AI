"""Deterministic MCP tool confidence grader (030.4)."""

from __future__ import annotations

from palatium_ai.application.agents.researcher.parsing import score_mcp_tool_confidence


def test_mcp_error_is_zero() -> None:
    assert score_mcp_tool_confidence(is_error=True, summary_chars=2_000) == 0.0


def test_mcp_empty_is_low_partial() -> None:
    assert score_mcp_tool_confidence(is_error=False, summary_chars=0) == 0.15


def test_mcp_short_evidence_below_typical_threshold() -> None:
    score = score_mcp_tool_confidence(is_error=False, summary_chars=50)
    assert 0.4 <= score < 0.7


def test_mcp_long_evidence_saturates() -> None:
    score = score_mcp_tool_confidence(is_error=False, summary_chars=5_000)
    assert score == 0.85

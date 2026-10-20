"""Per-tool MCP payload budgets for the Researcher synthesis prompt (065)."""

from __future__ import annotations

from palatium_ai.application.agents.researcher.config import (
    READ_ATTACHMENT_OUTPUT_MAX_CHARS,
    researcher_tool_output_budget,
)
from palatium_ai.domain.memory.budget import DEFAULT_PROMPT_BUDGET


def test_read_attachment_gets_a_document_budget_not_the_envelope_budget() -> None:
    """A thread-file re-read is evidence; 3000 chars would cut it to a snippet."""
    budget = researcher_tool_output_budget(
        server_name="platform",
        tool_name="read_attachment",
        default_max_chars=3_000,
    )

    assert budget == READ_ATTACHMENT_OUTPUT_MAX_CHARS
    assert budget > 3_000


def test_document_budget_stays_below_the_turn_attachment_budget() -> None:
    """One document read must still fit the prompt next to the turn's fence (065)."""
    assert DEFAULT_PROMPT_BUDGET.untrusted_context_max_chars > READ_ATTACHMENT_OUTPUT_MAX_CHARS


def test_retrieval_tools_keep_the_configured_envelope_budget() -> None:
    budget = researcher_tool_output_budget(
        server_name="platform",
        tool_name="search_knowledge",
        default_max_chars=3_000,
    )

    assert budget == 3_000


def test_operator_can_raise_the_global_budget_above_the_document_floor() -> None:
    budget = researcher_tool_output_budget(
        server_name="platform",
        tool_name="read_attachment",
        default_max_chars=16_000,
    )

    assert budget == 16_000

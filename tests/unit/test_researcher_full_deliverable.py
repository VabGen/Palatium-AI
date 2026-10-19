"""Researcher must emit full draft/compose bodies — not meta-only preambles (055)."""

from __future__ import annotations

from palatium_ai.application.agents.critic.prompts import CRITIC_SYSTEM_PROMPT
from palatium_ai.application.agents.researcher.config import (
    RESEARCHER_DEFAULT_MAX_TOKENS,
    RESEARCHER_GENERATION_MAX_TOKENS,
    SUMMARY_MAX_CHARS,
    researcher_completion_budget,
)
from palatium_ai.application.agents.researcher.parsing import parse_researcher_output
from palatium_ai.application.agents.researcher.prompts import RESEARCHER_SYSTEM_PROMPT


def test_researcher_prompt_requires_full_draft_body() -> None:
    prompt = RESEARCHER_SYSTEM_PROMPT.lower()
    assert "draft" in prompt
    assert "compose" in prompt
    assert "full deliverable" in prompt or "full deliverable body" in prompt
    assert "meta-description" in prompt
    assert "short answer" not in prompt


def test_researcher_prompt_requires_verbatim_extract_from_attachment() -> None:
    """Extract/full-text asks must copy OCR fence body, not summarize (Streaming 2026)."""
    prompt = RESEARCHER_SYSTEM_PROMPT.lower()
    assert "verbatim" in prompt
    assert "extract" in prompt
    assert "attached_files" in prompt
    # The prompt must not hand the model our internal field names — it echoes them
    # into user prose (055); the payload keys were renamed for the same reason.
    assert "attachment_context" not in prompt
    assert "основные пункты" in prompt or "paraphrase" in prompt
    assert "[attachment body truncated]" in RESEARCHER_SYSTEM_PROMPT


def test_researcher_prompt_uses_memory_for_identity() -> None:
    prompt = RESEARCHER_SYSTEM_PROMPT.lower()
    assert "identity" in prompt or "preference asks" in prompt
    assert "user_facts" in prompt
    assert "memory_hints" not in prompt
    assert "unsafe historical" in prompt or "refuse them" in prompt


def test_critic_prompt_rejects_meta_only_generation() -> None:
    prompt = CRITIC_SYSTEM_PROMPT.lower()
    assert "draft" in prompt
    assert "compose" in prompt
    assert "meta-only" in prompt or "meta-only promise" in prompt


def test_critic_prompt_uses_neutral_payload_names() -> None:
    """Internal field names must not reach an LLM prompt: the model echoes them into prose."""
    prompt = CRITIC_SYSTEM_PROMPT.lower()
    assert "attachment_context" not in prompt
    assert "attached_files" in prompt
    assert "prior_context" not in prompt
    assert "memory_hints" not in prompt


def test_generation_completion_budget_higher_than_default() -> None:
    assert researcher_completion_budget(()) == RESEARCHER_DEFAULT_MAX_TOKENS
    assert researcher_completion_budget(("search",)) == RESEARCHER_DEFAULT_MAX_TOKENS
    assert researcher_completion_budget(("draft",)) == RESEARCHER_GENERATION_MAX_TOKENS
    assert researcher_completion_budget(("compose",)) == RESEARCHER_GENERATION_MAX_TOKENS
    assert researcher_completion_budget(("draft", "search")) == RESEARCHER_GENERATION_MAX_TOKENS


def test_summary_clip_allows_full_letter_handoff() -> None:
    """SUMMARY_MAX_CHARS must not silently truncate a typical official reply."""
    body = (("Уважаемый Михаил Владимирович!\n\n" + ("Текст пункта. " * 40)) * 3).strip()
    assert len(body) > 1_000
    assert len(body) < SUMMARY_MAX_CHARS
    parsed = parse_researcher_output('{"summary": ' + __import__("json").dumps(body) + ', "confidence": 0.9, "sources_used": []}')
    assert parsed.summary == body
    assert not parsed.summary.endswith("…")

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
    """Critic-authored rules must not teach internal field names the model echoes into prose.

    Constitution articles (appended after ``CONSTITUTION —``) may name domain inputs
    such as ``memory_hints`` — that SoT is pinned separately in
    ``test_constitution_policy``. This gate covers only the Critic instruction body.
    """
    authored, _sep, _constitution = CRITIC_SYSTEM_PROMPT.partition("CONSTITUTION —")
    assert _sep, "Critic prompt must append the Constitution block"
    prompt = authored.lower()
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


def test_freeform_reason_only_prose_is_wrapped_not_raised() -> None:
    """reason_only text tasks may ignore json_object — do not kill the turn (030.8)."""
    prose = "1. Краткий пересказ: компания подписала соглашение.\n2. Парафраз: …"
    parsed = parse_researcher_output(prose)
    assert parsed.summary == prose
    assert 0.0 < parsed.confidence <= 1.0
    assert "llm_freeform" in parsed.sources_used

    as_string = parse_researcher_output('"просто текстовый ответ"')
    assert as_string.summary == "просто текстовый ответ"
    assert "llm_freeform" in as_string.sources_used

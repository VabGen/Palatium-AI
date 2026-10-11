"""strip_untrusted_tool_output keeps the body and leaves unclosed markers."""

from __future__ import annotations

from palatium_ai.domain.memory.tool_output import strip_untrusted_tool_output, wrap_untrusted_tool_output

_OPEN = "<<<UNTRUSTED_TOOL_OUTPUT source=mcp:platform.search_knowledge>>>"
_CLOSE = "<<<END_UNTRUSTED_TOOL_OUTPUT>>>"


def test_closed_envelope_fences_removed_body_kept() -> None:
    wrapped = wrap_untrusted_tool_output("Точный текст.", source="mcp:platform.search_knowledge")
    stripped = strip_untrusted_tool_output(wrapped)
    assert stripped.strip() == "Точный текст."
    assert _OPEN not in stripped
    assert _CLOSE not in stripped


def test_unclosed_envelope_is_left_intact() -> None:
    quoted = f"see {_OPEN} leftover"
    assert strip_untrusted_tool_output(quoted) == quoted


def test_two_closed_envelopes_keep_both_bodies() -> None:
    first = wrap_untrusted_tool_output("one", source="a")
    second = wrap_untrusted_tool_output("two", source="b")
    stripped = strip_untrusted_tool_output(first + second)
    assert stripped.strip().split() == ["one", "two"]
    assert "UNTRUSTED_TOOL_OUTPUT" not in stripped


def test_surrounding_text_and_body_are_kept() -> None:
    block = wrap_untrusted_tool_output("middle", source="a")
    stripped = strip_untrusted_tool_output(f"before\n{block}\nafter")
    assert "before" in stripped
    assert "middle" in stripped
    assert "after" in stripped
    assert "UNTRUSTED_TOOL_OUTPUT" not in stripped


def test_empty_string_stays_empty() -> None:
    assert strip_untrusted_tool_output("") == ""

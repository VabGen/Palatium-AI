"""prose_to_blocks — deterministic markdown/prose → ContentBlock (055)."""

from __future__ import annotations

from palatium_ai.domain.content.markdown_blocks import prose_to_blocks


def test_atx_heading_list_and_paragraph() -> None:
    source = "## Summary\n\nIntro paragraph.\n\n1. First item\n2. Second item\n\nClosing thoughts."
    title, blocks = prose_to_blocks(source)
    assert title is None
    assert blocks[0].type == "heading"
    assert blocks[0].text == "Summary"
    assert blocks[0].level == 2
    assert blocks[1].type == "paragraph"
    assert blocks[2].type == "list"
    assert blocks[2].style == "ordered"
    assert blocks[3].type == "paragraph"
    assert "Closing" in blocks[3].text


def test_fenced_code_block() -> None:
    source = "Before\n\n```python\nprint(1)\n```\n\nAfter"
    title, blocks = prose_to_blocks(source)
    assert title is None
    assert blocks[0].type == "paragraph"
    assert blocks[1].type == "code"
    assert blocks[1].language == "python"
    assert "print(1)" in blocks[1].content
    assert blocks[2].type == "paragraph"


def test_unclosed_fence_flushed() -> None:
    _, blocks = prose_to_blocks("```text\nline1\nline2")
    assert len(blocks) == 1
    assert blocks[0].type == "code"
    assert "line1" in blocks[0].content


def test_plain_passthrough_single_paragraph() -> None:
    title, blocks = prose_to_blocks("Just a sentence.")
    assert title is None
    assert len(blocks) == 1
    assert blocks[0].type == "paragraph"
    assert blocks[0].text == "Just a sentence."


def test_no_language_heuristic_without_fence() -> None:
    """Bare ``def`` / ``import`` lines stay paragraphs (055 — no language regex)."""
    source = "def foo():\n    return 1\nimport os"
    _, blocks = prose_to_blocks(source)
    assert all(block.type == "paragraph" for block in blocks)


def test_thesis_dump_stays_one_ordered_list() -> None:
    """Live regression: blank lines + body between markers must not restart at 1."""
    source = (
        "1. **Вступление** — кратко о правах детей с аутизмом.\n"
        "\n"
        "1. По вопросу назначения сопровождающего (ЦКРОиР)\n"
        "\n"
        "Родители жалуются на отсутствие тьюторов.\n"
        "\n"
        "ЦКРОиР отказывает в назначении.\n"
        "\n"
        "2. По вопросу штатной численности и режима работы тьютора (УО)\n"
        "\n"
        "Штатная единица отсутствует.\n"
        "\n"
        "3. **Координация** — нужно межведомственное взаимодействие.\n"
        "\n"
        "4. **Заключение** — системные нарушения требуют вмешательства.\n"
    )
    title, blocks = prose_to_blocks(source)
    assert title is None
    lists = [b for b in blocks if b.type == "list" and b.style == "ordered"]
    assert len(lists) == 1
    items = lists[0].items
    # Researcher may restart at 1.; continuity still yields one list (UI counters 1..n).
    assert len(items) == 5
    assert items[0].emphasis == "Вступление"
    assert "тьюторов" in items[1].text
    assert "Штатная" in items[2].text
    assert items[3].emphasis == "Координация"
    assert items[4].emphasis == "Заключение"


def test_closing_paragraph_after_list_not_swallowed() -> None:
    source = "1. First item\n2. Second item\n\nClosing thoughts."
    _, blocks = prose_to_blocks(source)
    assert blocks[0].type == "list"
    assert len(blocks[0].items) == 2
    assert blocks[1].type == "paragraph"
    assert "Closing" in blocks[1].text

"""Display strategy while a document streams (W1): what may show partial content.

``structured_incremental`` closes an element before painting it, which is correct but
late for prose. The policy decides per block type whether a prefix is already readable
(a paragraph) or would be misinformation (half a table, half a ``code`` body). These
tests pin the matrix — a new block type must be filed deliberately, not inherit
"stream everything" by omission.
"""

from __future__ import annotations

import json

import pytest

from palatium_ai.application.agents.formatter.partial_document import (
    PartialDocumentScanner,
    PartialFrame,
)
from palatium_ai.domain.content import ContentBlock
from palatium_ai.domain.policies.stream_display import StreamDisplayPolicy

BLOCK_TYPES = (
    "paragraph",
    "list",
    "steps",
    "table",
    "kv",
    "chart",
    "heading",
    "callout",
    "code",
    "formula",
    "divider",
    "widget",
)


@pytest.mark.parametrize("block_type", BLOCK_TYPES)
def test_every_block_type_has_an_explicit_strategy(block_type: str) -> None:
    assert StreamDisplayPolicy.strategy_for(block_type) in ("text_delta", "skeleton", "on_close")


def test_matrix_matches_the_contract() -> None:
    assert StreamDisplayPolicy.strategy_for("paragraph") == "text_delta"
    assert StreamDisplayPolicy.strategy_for("table") == "skeleton"
    assert StreamDisplayPolicy.strategy_for("list") == "skeleton"
    assert StreamDisplayPolicy.strategy_for("code") == "on_close"
    assert StreamDisplayPolicy.strategy_for("formula") == "on_close"


def test_unknown_block_type_waits_for_close() -> None:
    """Fail-safe: an unknown type is never streamed partially."""
    assert StreamDisplayPolicy.strategy_for("unknown_future_block") == "on_close"
    assert StreamDisplayPolicy.strategy_for("") == "on_close"


def test_strategy_is_case_and_whitespace_insensitive() -> None:
    assert StreamDisplayPolicy.strategy_for(" Paragraph ") == "text_delta"


def test_every_block_type_in_the_union_is_classified() -> None:
    """A block kind that exists in the contract cannot fall through to the default."""
    from typing import get_args

    members = get_args(get_args(ContentBlock)[0])
    kinds = {
        member.model_fields["type"].default for member in members if isinstance(member, type) and "type" in member.model_fields
    }
    assert kinds == set(BLOCK_TYPES)


def _stream(raw: str, chunk_size: int) -> list[PartialFrame]:
    scanner = PartialDocumentScanner()
    frames: list[PartialFrame] = []
    for start in range(0, len(raw), chunk_size):
        frames.extend(scanner.feed(raw[start : start + chunk_size]))
    frames.extend(scanner.pending())
    return frames


def _render(frames: list[PartialFrame]) -> str:
    out = ""
    for frame in frames:
        if not frame.text:
            continue
        if out and not frame.continues_prose:
            out += "\n\n"
        out += frame.text
    return out


@pytest.mark.parametrize("chunk_size", (1, 2, 5, 11))
def test_open_paragraph_prose_arrives_before_the_block_closes(chunk_size: int) -> None:
    """The whole point of W1: text is painted while the element is still open."""
    text = "Договор вступает в силу с момента подписания сторонами."
    raw = json.dumps({"blocks": [{"type": "paragraph", "text": text}]}, ensure_ascii=False)
    stop = raw.index("подписания") + len("подписания")

    frames = _stream(raw[:stop], chunk_size)
    partial = [frame for frame in frames if frame.block is None and frame.text]

    assert partial, "an open paragraph must paint its prefix"
    assert all(frame.index == 0 for frame in partial)
    assert text.startswith("".join(frame.text for frame in partial))
    assert all(frame.block is None for frame in frames), "no typed block before close"


@pytest.mark.parametrize("chunk_size", (1, 2, 5, 11))
def test_streamed_prefix_plus_remainder_equals_the_block_text(chunk_size: int) -> None:
    """Vercel ``streamObject`` superset rule: nothing painted is ever rewritten."""
    text = "Первая часть. Вторая часть — с «кавычками» и тире."
    raw = json.dumps({"blocks": [{"type": "paragraph", "text": text}]}, ensure_ascii=False)

    frames = _stream(raw, chunk_size)
    rendered = _render(frames)

    assert rendered == text
    assert sum(1 for frame in frames if frame.block is not None) == 1
    # Prefix frames + the closing remainder: no character painted twice, none lost.
    assert "".join(frame.text for frame in frames if frame.index >= 0) == text


@pytest.mark.parametrize("chunk_size", (1, 2, 3, 7))
def test_escapes_survive_a_chunk_boundary(chunk_size: int) -> None:
    """A split ``\\n``/``\\u00e9``/surrogate pair must never paint a wrong character."""
    text = 'Строка 1\nСтрока 2 — café 🚀 "кавычки" \\ слэш'
    raw = json.dumps({"blocks": [{"type": "paragraph", "text": text}]}, ensure_ascii=False)

    frames = _stream(raw, chunk_size)

    assert _render(frames) == text
    assert all("\ufffd" not in frame.text for frame in frames)


def test_non_streaming_blocks_never_paint_partial_content() -> None:
    """A half table / half code body is misinformation, not progress."""
    table = json.dumps(
        {"blocks": [{"type": "table", "columns": ["a", "b"], "rows": [["1", "2"], ["3", "4"]]}]},
        ensure_ascii=False,
    )
    code = json.dumps(
        {"blocks": [{"type": "code", "language": "python", "content": "print('hi')"}]},
        ensure_ascii=False,
    )

    cases = (
        (table, table.index('"2"')),
        (code, code.index("print")),
    )
    for raw, cutoff in cases:
        frames = _stream(raw[:cutoff], 3)
        assert [frame for frame in frames if frame.text] == []


def test_paragraph_does_not_stream_before_its_type_is_known() -> None:
    """Paint only when the type is known to be a paragraph — order matters."""
    raw = '{"blocks":[{"text":"Частичный текст","type":"heading","level":2}]}'
    frames = _stream(raw[: raw.index('"type"')], 4)

    assert [frame for frame in frames if frame.text] == []

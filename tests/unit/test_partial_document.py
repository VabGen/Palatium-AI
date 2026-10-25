"""Incremental ContentDocument scanning: closed blocks become paint-able frames.

The scanner is the only thing standing between "provider streams JSON" and "user
sees words", so its contract is narrow and testable without an LLM: feed chunks,
get back frames in document order — prose for ``answer_delta`` and a validated
typed block for ``block_delta`` — never a half-decoded string.
"""

from __future__ import annotations

import json

import pytest

from palatium_ai.application.agents.formatter.partial_document import (
    PartialDocumentScanner,
    PartialFrame,
)
from palatium_ai.domain.content import CodeBlock, ContentDocument, ListBlock, TableBlock

DOCUMENT = {
    "schema_version": 1,
    "locale": "ru-RU",
    "title": "Сравнение файлов",
    "blocks": [
        {"type": "heading", "level": 2, "text": "Отличия"},
        {"type": "paragraph", "text": "В первой версии нет раздела 3."},
        {
            "type": "list",
            "style": "unordered",
            "items": [{"text": "Изменён заголовок"}, {"text": "Удалён пункт 4"}],
        },
        {"type": "callout", "tone": "warning", "title": "Важно", "body": "Проверьте дату."},
        {"type": "code", "language": "python", "content": "print('hi')"},
    ],
    "meta": {"confidence": 0.9},
}
RAW = json.dumps(DOCUMENT, ensure_ascii=False)


def _feed_all(chunk_size: int) -> list[PartialFrame]:
    scanner = PartialDocumentScanner()
    frames: list[PartialFrame] = []
    for start in range(0, len(RAW), chunk_size):
        frames.extend(scanner.feed(RAW[start : start + chunk_size]))
    frames.extend(scanner.pending())
    return frames


def _prose(frames: list[PartialFrame]) -> list[str]:
    return [frame.text for frame in frames if frame.text]


def _render(frames: list[PartialFrame]) -> str:
    """What the append-only prose preview shows after all frames (client accumulator)."""
    out = ""
    for frame in frames:
        if not frame.text:
            continue
        if out and not frame.continues_prose:
            out += "\n\n"
        out += frame.text
    return out


@pytest.mark.parametrize("chunk_size", (1, 3, 7, 40, len(RAW)))
def test_frames_are_stable_across_chunk_boundaries(chunk_size: int) -> None:
    """A token boundary may fall anywhere — mid-string, mid-escape, mid-object.

    The *frame list* legitimately depends on chunking (an open paragraph streams per
    delta), so the invariant is the rendered preview: the user must read exactly the
    same text no matter how the provider split the JSON.
    """
    frames = _feed_all(chunk_size)
    joined = _render(frames)

    assert joined == _render(_feed_all(2)), "preview must not depend on provider chunking"
    assert joined.startswith("Сравнение файлов")
    assert "Отличия" in joined
    assert "В первой версии нет раздела 3." in joined
    assert "Изменён заголовок" in joined
    assert "Удалён пункт 4" in joined
    assert "Важно" in joined
    assert "Проверьте дату." in joined
    # Layout-only fields and code bodies are not prose for the text preview.
    assert "print('hi')" not in joined


def test_typed_blocks_match_the_final_document() -> None:
    """block_delta payloads are exactly the document blocks — no preview-only shape."""
    frames = _feed_all(5)
    typed = [frame.block for frame in frames if frame.block is not None]

    document = ContentDocument.model_validate(DOCUMENT)
    assert typed == list(document.blocks)
    assert [frame.index for frame in frames if frame.block is not None] == [0, 1, 2, 3, 4]
    code = typed[4]
    assert isinstance(code, CodeBlock)
    assert code.content == "print('hi')"  # kept in the typed frame, not as prose
    assert isinstance(typed[2], ListBlock)
    assert len(typed[2].items) == 2


def test_nothing_is_emitted_twice() -> None:
    joined = _render(_feed_all(5))
    assert joined.count("Проверьте дату.") == 1
    assert joined.count("Отличия") == 1


def test_partial_object_is_not_painted() -> None:
    scanner = PartialDocumentScanner()
    truncated = RAW[: RAW.index('"Проверьте дату."') + len('"Проверьте дату.')]
    frames = scanner.feed(truncated)

    joined = "\n\n".join(_prose(frames))
    assert "Сравнение файлов" in joined
    assert "Проверьте дату" not in joined  # the block never closed
    assert all(frame.block is not None or frame.index == -1 for frame in frames)


def test_unterminated_escape_does_not_break_the_scan() -> None:
    scanner = PartialDocumentScanner()
    scanner.feed('{"title":"a\\')
    frames = scanner.feed('"b","blocks":[{"type":"paragraph","text":"ok"}]}')
    assert _prose(frames) == ['a"b', "ok"]
    assert frames[-1].block is not None


def test_title_is_taken_from_the_root_not_a_callout() -> None:
    """A callout title must not be promoted to the document title."""
    raw = json.dumps(
        {
            "locale": "ru-RU",
            "blocks": [{"type": "callout", "tone": "info", "title": "Внутренний", "body": "Тело"}],
            "meta": {"confidence": 0.5},
        },
        ensure_ascii=False,
    )
    scanner = PartialDocumentScanner()
    frames = scanner.feed(raw)
    # Emitted as its own block, not promoted to the document title.
    assert _prose(frames) == ["Внутренний\n\nТело"]
    assert frames[0].index == 0


def test_invalid_closed_block_is_skipped_without_losing_the_rest() -> None:
    scanner = PartialDocumentScanner()
    frames = scanner.feed('{"blocks":[{"type":"paragraph",,},{"type":"paragraph","text":"Живой блок"}]}')
    assert _prose(frames) == ["Живой блок"]
    assert frames[0].index == 1


def test_block_with_ragged_table_is_not_painted_as_a_typed_frame() -> None:
    """Cross-field invariants are not JSON Schema; a broken block must not paint typed."""
    raw = json.dumps(
        {
            "blocks": [
                {
                    "type": "table",
                    "columns": ["a", "b"],
                    "rows": [["1", "2"], ["3"]],
                }
            ]
        }
    )
    frames = PartialDocumentScanner().feed(raw)

    # No prose and no typed block: painting it would promise a document that the
    # final contract rejects.
    assert frames == []


def test_typed_frame_validation_matches_document_validation() -> None:
    """A table accepted as a typed frame is also accepted by the document contract."""
    raw = json.dumps(
        {
            "blocks": [
                {
                    "type": "table",
                    "columns": ["a", "b"],
                    "rows": [["1", "2"], ["3", "4"]],
                }
            ]
        }
    )
    frame = PartialDocumentScanner().feed(raw)[0]

    assert isinstance(frame.block, TableBlock)
    ContentDocument.model_validate({"locale": "en-US", "blocks": [frame.block], "meta": {"confidence": 1}})


def test_blocks_array_closing_stops_scanning() -> None:
    scanner = PartialDocumentScanner()
    frames = scanner.feed('{"blocks":[{"type":"paragraph","text":"a"}],"meta":{}}')
    assert _prose(frames) == ["a"]
    # Further deltas cannot resurrect blocks from the (already closed) array.
    assert scanner.feed('{"type":"paragraph","text":"b"}') == []

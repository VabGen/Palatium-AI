# src/palatium_ai/application/agents/formatter/partial_document.py

"""Incremental ``ContentDocument`` scanner: closed blocks become user-visible frames.

``schema_first`` asks the provider for a ``json_schema`` document. The provider
streams that JSON token by token, but raw JSON is not something a user can read, so
the turn used to stay silent until the whole document validated — then the finished
``ContentDocument`` replaced whatever draft was on screen.

This scanner turns the same stream into paint-able units without a second LLM call
and without a second contract: every time a ``blocks[]`` element closes, it yields
one :class:`PartialFrame` carrying

- ``text`` — the block prose, the append-only ``answer_delta`` preview that older
  clients already know how to render;
- ``block`` — the same element validated as a typed ``ContentBlock``, which the
  client renders through the final ``BlockRenderer`` (``block_delta``). Both come
  from one parse, so preview and result cannot disagree about the content.

The final document is therefore a **superset** of what the user already reads,
which is what makes ``replace`` unnecessary (Vercel ``streamObject`` / OpenAI
partial structured-output semantics).

Design notes:

- stdlib only. Blocks are small and objects are only accepted once balanced, so
  re-scanning the accumulated prefix per chunk is cheap and keeps the state machine
  honest (no half-tracked escapes across chunks). A dependency such as ``jiter`` is
  a separate decision (025/phase plan), not a prerequisite.
- A complete-but-invalid element is skipped as a typed block, never fatal: the
  schema-first contract already has a legacy fallback path for a document that
  fails validation. Its prose (if any) still paints, so the text is not lost.
- Prose only in ``text``. ``code``/``formula`` bodies are user content and are kept
  in the typed block; layout keys (``icon``, ``tone``, ``level``) are not prose.
"""

from __future__ import annotations

import json
import re

from dataclasses import dataclass

from pydantic import TypeAdapter, ValidationError

from palatium_ai.core.logging import get_logger
from palatium_ai.domain.content import ContentBlock, validate_content_block

logger = get_logger(__name__)

_BLOCKS_KEY_RE = re.compile(r'"blocks"\s*:\s*\[')
_TITLE_KEY_RE = re.compile(r'"title"\s*:\s*"')
#: Document keys that carry user-readable prose. ``title``/``body`` cover callouts,
#: ``text`` covers paragraphs, headings, list items, table cells and steps.
_PROSE_KEYS = frozenset({"text", "title", "body"})
#: Built once: the block union is frozen, and per-block adapter construction would
#: rebuild the same validators on every streamed element.
_BLOCK_ADAPTER: TypeAdapter[ContentBlock] = TypeAdapter(ContentBlock)


@dataclass(frozen=True, slots=True)
class PartialFrame:
    """One unit that just closed in the streamed document.

    ``text`` is what the append-only prose preview paints (``answer_delta``);
    ``block`` is the validated typed payload when the element matched the block
    union (``block_delta``). ``index`` is the element position in ``blocks[]``;
    the document title uses ``index == -1`` and never carries a block.
    """

    text: str = ""
    block: ContentBlock | None = None
    index: int = -1


class PartialDocumentScanner:
    """Accumulates streamed document JSON and yields newly closed frames."""

    __slots__ = ("_buffer", "_emitted_blocks", "_title_emitted")

    def __init__(self) -> None:
        self._buffer = ""
        self._emitted_blocks = 0
        self._title_emitted = False

    def feed(self, chunk: str) -> list[PartialFrame]:
        """Add a streamed chunk; return frames that became available."""
        if not chunk:
            return []
        self._buffer += chunk
        return self._new_frames()

    def pending(self) -> list[PartialFrame]:
        """Everything still un-emitted at end of stream (truncation-tolerant)."""
        return self._new_frames()

    def _new_frames(self) -> list[PartialFrame]:
        out: list[PartialFrame] = []
        if not self._title_emitted:
            title = _root_title(self._buffer)
            if title:
                out.append(PartialFrame(text=title))
                self._title_emitted = True
        blocks = _closed_block_objects(self._buffer)
        for raw in blocks[self._emitted_blocks :]:
            index = self._emitted_blocks
            self._emitted_blocks += 1
            frame = _frame_from_block(raw, index)
            if frame is not None:
                out.append(frame)
        return out


def _frame_from_block(raw: str, index: int) -> PartialFrame | None:
    """Parse one closed element; typed block when valid, prose either way."""
    try:
        node = json.loads(raw)
    except json.JSONDecodeError:
        logger.warning("formatter.partial_parse.block_skipped", chars=len(raw))
        return None
    parts: list[str] = []
    _collect_prose(node, parts)
    text = "\n\n".join(parts)
    block = _typed_block(node, index)
    if not text and block is None:
        return None
    return PartialFrame(text=text, block=block, index=index)


def _typed_block(node: object, index: int) -> ContentBlock | None:
    """Validate the element against the block union; ``None`` when it does not fit."""
    try:
        block = _BLOCK_ADAPTER.validate_python(node)
        validate_content_block(block)
    except ValidationError, ValueError:
        # The provider enforces the schema, so this is a contract signal, not a
        # reason to drop the turn — the prose preview and the final document still
        # have a chance to be correct (050: no silent truncation of the answer).
        logger.warning("formatter.partial_parse.block_invalid", index=index)
        return None
    return block


def _root_title(buffer: str) -> str | None:
    """Document ``title`` only — a callout title belongs to its own block."""
    blocks_at = _blocks_start(buffer)
    limit = blocks_at if blocks_at >= 0 else len(buffer)
    match = _TITLE_KEY_RE.search(buffer, 0, limit)
    if match is None:
        return None
    return _complete_json_string(buffer, match.end() - 1)


def _complete_json_string(buffer: str, quote_at: int) -> str | None:
    """Decode the JSON string literal starting at ``quote_at``; None while incomplete."""
    index = quote_at + 1
    escaped = False
    while index < len(buffer):
        char = buffer[index]
        if escaped:
            escaped = False
        elif char == "\\":
            escaped = True
        elif char == '"':
            try:
                value = json.loads(buffer[quote_at : index + 1])
            except json.JSONDecodeError:
                return None
            return value.strip() if isinstance(value, str) and value.strip() else None
        index += 1
    return None


def _blocks_start(buffer: str) -> int:
    match = _BLOCKS_KEY_RE.search(buffer)
    return match.end() if match is not None else -1


def _closed_block_objects(buffer: str) -> list[str]:
    """Raw JSON of every balanced element of the top-level ``blocks`` array."""
    start = _blocks_start(buffer)
    if start < 0:
        return []
    objects: list[str] = []
    index = start
    while index < len(buffer):
        char = buffer[index]
        if char in " \t\r\n,":
            index += 1
            continue
        if char != "{":
            break  # the blocks array closed (``]``) or the payload is malformed
        end = _balanced_object_end(buffer, index)
        if end < 0:
            break  # element still streaming
        objects.append(buffer[index : end + 1])
        index = end + 1
    return objects


def _balanced_object_end(buffer: str, start: int) -> int:
    """Index of the ``}`` matching the ``{`` at ``start``; -1 while incomplete."""
    depth = 0
    in_string = False
    escaped = False
    for index in range(start, len(buffer)):
        char = buffer[index]
        if in_string:
            if escaped:
                escaped = False
            elif char == "\\":
                escaped = True
            elif char == '"':
                in_string = False
            continue
        if char == '"':
            in_string = True
        elif char in "[{":
            depth += 1
        elif char in "]}":
            depth -= 1
            if depth == 0:
                return index
    return -1


def _collect_prose(node: object, parts: list[str]) -> None:
    if isinstance(node, dict):
        for key, value in node.items():
            if key in _PROSE_KEYS and isinstance(value, str) and value.strip():
                parts.append(value.strip())
            elif isinstance(value, dict | list):
                _collect_prose(value, parts)
    elif isinstance(node, list):
        for item in node:
            _collect_prose(item, parts)


__all__ = ["PartialDocumentScanner", "PartialFrame"]

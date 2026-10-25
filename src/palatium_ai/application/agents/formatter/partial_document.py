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
from palatium_ai.domain.content import ContentBlock, ParagraphBlock, validate_content_block
from palatium_ai.domain.policies.internal_vocabulary import InternalVocabularyPolicy
from palatium_ai.domain.policies.stream_display import StreamDisplayPolicy

logger = get_logger(__name__)

_BLOCKS_KEY_RE = re.compile(r'"blocks"\s*:\s*\[')
_TITLE_KEY_RE = re.compile(r'"title"\s*:\s*"')
_TEXT_KEY_RE = re.compile(r'"text"\s*:\s*"')
_BLOCK_TYPE_RE = re.compile(r'"type"\s*:\s*"([a-z_]+)"')
#: Document keys that carry user-readable prose. ``title``/``body`` cover callouts,
#: ``text`` covers paragraphs, headings, list items, table cells and steps.
_PROSE_KEYS = frozenset({"text", "title", "body"})
_STRING_ESCAPES = {
    '"': '"',
    "\\": "\\",
    "/": "/",
    "b": "\b",
    "f": "\f",
    "n": "\n",
    "r": "\r",
    "t": "\t",
}
_HEX4_RE = re.compile(r"[0-9a-fA-F]{4}")
#: Built once: the block union is frozen, and per-block adapter construction would
#: rebuild the same validators on every streamed element.
#: ``ContentBlock`` is an ``Annotated`` discriminated union — a valid runtime type
#: form that pyright's ``TypeForm`` (PEP 747) check does not model: TOOL_LIMITATION (017).
_BLOCK_ADAPTER: TypeAdapter[ContentBlock] = TypeAdapter(ContentBlock)  # pyright: ignore[reportArgumentType]


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
    #: ``text`` continues the previous frame without a paragraph break. Only an open
    #: ``paragraph`` streamed in several deltas (and its closing remainder) sets it:
    #: inserting "\n\n" mid-sentence would break the sentence the user is reading.
    continues_prose: bool = False


class PartialDocumentScanner:
    """Accumulates streamed document JSON and yields newly closed frames."""

    __slots__ = ("_buffer", "_emitted_blocks", "_prose_emitted", "_prose_index", "_title_emitted")

    def __init__(self) -> None:
        self._buffer = ""
        self._emitted_blocks = 0
        self._title_emitted = False
        # Index of the open block whose prose is streaming, and how many of its
        # decoded characters the client already has (append-only bookkeeping).
        self._prose_index = -1
        self._prose_emitted = 0

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
        blocks, closed_end = _closed_objects(self._buffer)
        for raw in blocks[self._emitted_blocks :]:
            index = self._emitted_blocks
            self._emitted_blocks += 1
            already = self._prose_emitted if index == self._prose_index else 0
            frame = _frame_from_block(raw, index, already_emitted=already)
            if index == self._prose_index:
                self._prose_index = -1
                self._prose_emitted = 0
            if frame is not None:
                out.append(frame)
        out.extend(self._open_prose_frames(closed_end))
        return out

    def _open_prose_frames(self, closed_end: int) -> list[PartialFrame]:
        """Prose of the element that is still open, when its type allows it.

        The type must already be known to be a ``paragraph`` — a delta painted before
        ``"type"`` arrives could turn out to be a heading or a table cell, and the
        strategy matrix would be violated after the fact. Nothing is emitted unless
        the block type is known and streams by policy (W1).
        """
        open_at = _open_object_start(self._buffer, closed_end)
        if open_at < 0:
            self._prose_index = -1
            self._prose_emitted = 0
            return []
        region = self._buffer[open_at:]
        type_match = _BLOCK_TYPE_RE.search(region)
        if type_match is None or not StreamDisplayPolicy.partial_prose_allowed(type_match.group(1)):
            return []
        text_at = _TEXT_KEY_RE.search(region, type_match.end())
        if text_at is None:
            return []
        decoded = _decode_json_string_prefix(region, text_at.end() - 1)
        index = self._emitted_blocks
        if index != self._prose_index:
            # A new element opened: its prose starts a new paragraph.
            self._prose_index = index
            self._prose_emitted = 0
        pending = decoded[self._prose_emitted :]
        # Never split an internal marker across frames (020): hold the tail back and
        # let the next delta — or the closing frame — deliver it sanitised.
        cut = InternalVocabularyPolicy.safe_cut(pending)
        if cut <= 0:
            return []
        started = self._prose_emitted > 0
        self._prose_emitted += cut
        return [PartialFrame(text=pending[:cut], index=index, continues_prose=started)]


def _frame_from_block(raw: str, index: int, *, already_emitted: int = 0) -> PartialFrame | None:
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
    if isinstance(block, ParagraphBlock):
        # The streamed prefix is a prefix of the validated ``text`` — trusting the
        # contract here (not the raw decode) keeps prefix + remainder == block.text
        # even when an escape was held back (Vercel ``streamObject`` superset rule).
        text = block.text[already_emitted:]
    return PartialFrame(text=text, block=block, index=index, continues_prose=already_emitted > 0)


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


def _closed_objects(buffer: str) -> tuple[list[str], int]:
    """Raw JSON of every balanced element of ``blocks[]``, plus the scan position.

    The returned offset is where scanning stopped — right after the last closed
    element, or at the ``]`` that closed the array. The open element (if any) starts
    there, which is what partial-prose streaming needs.
    """
    start = _blocks_start(buffer)
    if start < 0:
        return [], -1
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
    return objects, index


def _open_object_start(buffer: str, scan_from: int) -> int:
    """Index of the ``{`` of the element that is still open, -1 when there is none."""
    if scan_from < 0:
        return -1
    index = scan_from
    while index < len(buffer) and buffer[index] in " \t\r\n,":
        index += 1
    return index if index < len(buffer) and buffer[index] == "{" else -1


def _decode_json_string_prefix(buffer: str, quote_at: int) -> str:
    """Decode as much of the JSON string literal at ``quote_at`` as is complete.

    Stops before anything that could still change meaning: an escape split across
    chunks (``u00`` → ``u00e9``), a lone high surrogate that cannot be UTF-8
    encoded, or an escape JSON does not define. Whatever is held back is delivered by
    the closing frame from the validated block, so the painted prefix is always a
    prefix of the final text (no layout shift, no wrong character).
    """
    out: list[str] = []
    index = quote_at + 1
    length = len(buffer)
    while index < length:
        char = buffer[index]
        if char == '"':
            break
        if char != "\\":
            out.append(char)
            index += 1
            continue
        if index + 1 >= length:
            break
        marker = buffer[index + 1]
        if marker == "u":
            decoded = _decode_unicode_escape(buffer, index, length)
            if decoded is None:
                break
            text, consumed = decoded
            out.append(text)
            index += consumed
            continue
        replacement = _STRING_ESCAPES.get(marker)
        if replacement is None:
            break  # malformed escape: let the closed block be authoritative
        out.append(replacement)
        index += 2
    return "".join(out)


def _decode_unicode_escape(buffer: str, index: int, length: int) -> tuple[str, int] | None:
    """Decode ``uXXXX`` (with its surrogate pair) at ``index``; None while incomplete."""
    if index + 6 > length:
        return None
    digits = buffer[index + 2 : index + 6]
    if _HEX4_RE.fullmatch(digits) is None:
        return None
    code = int(digits, 16)
    if not 0xD800 <= code <= 0xDBFF:
        return chr(code), 6
    if index + 12 > length:
        return None
    low_digits = buffer[index + 8 : index + 12]
    if buffer[index + 6 : index + 8] != "\\u" or _HEX4_RE.fullmatch(low_digits) is None:
        return None
    low = int(low_digits, 16)
    if not 0xDC00 <= low <= 0xDFFF:
        return None
    return chr(0x10000 + ((code - 0xD800) << 10) + (low - 0xDC00)), 12


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

# src/palatium_ai/application/agents/formatter/answer_delta.py

"""Emit early user-facing prose over SSE (TTFT) without waiting for Formatter LLM."""

from __future__ import annotations

import time

from palatium_ai.application.services.turn_sse_bridge import TurnSseBridge, get_turn_sse_bridge
from palatium_ai.core.observability.metrics import agent_metrics
from palatium_ai.domain.content import ContentBlock
from palatium_ai.domain.policies.internal_vocabulary import InternalVocabularyPolicy

# Chunk size for progressive pending UI; prefer newline boundaries.
_ANSWER_DELTA_CHUNK_CHARS = 512


def emit_answer_deltas(prose: str, *, replace: bool | None = None) -> None:
    """Fan out ready prose as ``answer_delta`` events when a turn SSE bridge is bound.

    Subsequent full-draft emits set ``replace=True`` so the client resets its
    accumulator (worker → revision → formatter) instead of concatenating twice.

    Single funnel for every streamed draft (worker early emit, cache, fast path,
    deterministic emit, formatted plain text) — and therefore the one place where
    internal contract vocabulary must be stripped before it reaches the client
    (020: a guardrail in code, not a prompt request) and where the one-reset-per-turn
    invariant is enforced (055).
    """
    text = InternalVocabularyPolicy.sanitize_text(prose).strip()
    if not text:
        return
    bridge = get_turn_sse_bridge()
    if bridge is None:
        return
    # A draft re-emitted after the user already reads it (e.g. the worker summary
    # painted in researcher_node and re-emitted in formatter_node) repaints identical
    # pixels: skip it instead of flickering (040: layout_shift_count must stay 0).
    if replace is not True and bridge.answer_already_painted(text):
        return
    want_replace = bridge.has_emitted_answer if replace is None else replace
    do_replace = bridge.answer_replace_allowed(want_replace=want_replace)
    _queue_frames(bridge, text, replace=do_replace)


def emit_structured_answer_delta(prose: str, *, separator: str = "", keep_whitespace: bool = False) -> None:
    """Append one prose fragment of a streamed ``ContentDocument`` (structured contract).

    Fragments are document blocks that have just closed, so each one is new content:
    the duplicate guard of ``emit_answer_deltas`` does not apply (a document may
    legitimately repeat a paragraph), while the no-replace invariant does — the
    final ``result`` document is a superset of what the user already reads, so it
    never has to repaint the preview (Vercel ``streamObject`` semantics).

    ``keep_whitespace`` is for a fragment that continues the same paragraph
    (``PartialFrame.continues_prose``): stripping it would delete the space at the
    delta boundary and glue two words together in the client's accumulator.
    """
    text = InternalVocabularyPolicy.sanitize_text(prose)
    if not keep_whitespace:
        text = text.strip()
    # A whitespace-only continuation frame is meaningful (it is the space between two
    # words split across deltas); only a non-continuation frame may be empty.
    if not text or (not keep_whitespace and not text.strip()):
        return
    bridge = get_turn_sse_bridge()
    if bridge is None:
        return
    _queue_frames(bridge, f"{separator}{text}", replace=False)


def emit_document_title(title: str) -> None:
    """Queue the structured document title (typed preview, before the first block).

    The title is not a block, but the user reads it above the blocks: painting it as
    plain prose first and then switching to the block preview would move the text.
    One typed frame keeps the preview additive from the very first pixel.
    """
    text = InternalVocabularyPolicy.sanitize_text(title).strip()
    if not text:
        return
    bridge = get_turn_sse_bridge()
    if bridge is None:
        return
    bridge.emit_nowait({"event": "document_title", "title": text})
    _mark_visible(bridge)


def emit_document_block(*, index: int, block: ContentBlock) -> None:
    """Queue one typed ``block_delta`` frame (structured incremental preview).

    The frame carries a block that already validated against the document contract,
    so the client renders it through the same ``BlockRenderer`` as the final answer
    instead of re-parsing prose (one renderer, one contract). Like the prose frames,
    ``block_delta`` is append-only and never carries ``replace``: the final document
    is a superset of the painted blocks (040: ``layout_shift_count == 0``).
    """
    bridge = get_turn_sse_bridge()
    if bridge is None:
        return
    clean = InternalVocabularyPolicy.sanitize_block(block)
    if clean is None:
        # Only our own notation was in the block (page address / style keyword):
        # there is nothing to paint, and the final document will not contain it.
        return
    bridge.emit_nowait({"event": "block_delta", "index": index, "block": clean.model_dump(mode="json")})
    if not bridge.sse_first_block_recorded:
        bridge.sse_first_block_recorded = True
        agent_metrics.record_sse_first_block(time.perf_counter() - bridge.started_at)
    _mark_visible(bridge)


def _queue_frames(bridge: TurnSseBridge, text: str, *, replace: bool) -> None:
    """Chunk ``text`` into answer_delta frames; ``replace`` only on the first one."""
    chunks = _chunk_prose(text, max_chars=_ANSWER_DELTA_CHUNK_CHARS)
    for index, chunk in enumerate(chunks):
        payload: dict[str, object] = {"event": "answer_delta", "delta": chunk}
        frame_replace = replace and index == 0
        if frame_replace:
            payload["replace"] = True
            agent_metrics.record_sse_layout_shift(contract="legacy_markdown")
        bridge.emit_nowait(payload)
        bridge.record_answer_frame(chunk, replace=frame_replace)
    _mark_visible(bridge)


def _mark_visible(bridge: TurnSseBridge) -> None:
    """First user-visible frame (prose or block) opens the SSE TTFT budget."""
    bridge.has_emitted_answer = True
    if not bridge.sse_ttft_recorded:
        bridge.sse_ttft_recorded = True
        agent_metrics.record_sse_ttft(time.perf_counter() - bridge.started_at)


def _chunk_prose(text: str, *, max_chars: int) -> list[str]:
    if max_chars < 1 or len(text) <= max_chars:
        return [text]
    chunks: list[str] = []
    start = 0
    while start < len(text):
        end = min(start + max_chars, len(text))
        if end < len(text):
            split_at = text.rfind("\n", start, end)
            if split_at <= start:
                split_at = text.rfind(" ", start, end)
            if split_at > start:
                end = split_at + 1
        piece = text[start:end]
        if piece:
            chunks.append(piece)
        start = end if end > start else start + max_chars
    return chunks or [text]

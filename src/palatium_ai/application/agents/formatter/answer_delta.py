# src/palatium_ai/application/agents/formatter/answer_delta.py

"""Emit early user-facing prose over SSE (TTFT) without waiting for Formatter LLM."""

from __future__ import annotations

import time

from palatium_ai.application.services.turn_sse_bridge import get_turn_sse_bridge
from palatium_ai.core.observability.metrics import agent_metrics
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
    chunks = _chunk_prose(text, max_chars=_ANSWER_DELTA_CHUNK_CHARS)
    for index, chunk in enumerate(chunks):
        payload: dict[str, object] = {"event": "answer_delta", "delta": chunk}
        frame_replace = do_replace and index == 0
        if frame_replace:
            payload["replace"] = True
            agent_metrics.record_sse_layout_shift(contract="legacy_markdown")
        bridge.emit_nowait(payload)
        bridge.record_answer_frame(chunk, replace=frame_replace)
    if not bridge.sse_ttft_recorded:
        bridge.sse_ttft_recorded = True
        agent_metrics.record_sse_ttft(time.perf_counter() - bridge.started_at)
    bridge.has_emitted_answer = True


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

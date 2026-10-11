# src/palatium_ai/application/agents/formatter/answer_delta.py

"""Emit early user-facing prose over SSE (TTFT) without waiting for Formatter LLM."""

from __future__ import annotations

import time

from palatium_ai.application.services.turn_sse_bridge import get_turn_sse_bridge
from palatium_ai.core.observability.metrics import agent_metrics

# Chunk size for progressive pending UI; prefer newline boundaries.
_ANSWER_DELTA_CHUNK_CHARS = 512


def emit_answer_deltas(prose: str, *, replace: bool | None = None) -> None:
    """Fan out ready prose as ``answer_delta`` events when a turn SSE bridge is bound.

    Subsequent full-draft emits set ``replace=True`` so the client resets its
    accumulator (worker → revision → formatter) instead of concatenating twice.
    """
    text = prose.strip()
    if not text:
        return
    bridge = get_turn_sse_bridge()
    if bridge is None:
        return
    do_replace = bridge.has_emitted_answer if replace is None else replace
    chunks = _chunk_prose(text, max_chars=_ANSWER_DELTA_CHUNK_CHARS)
    for index, chunk in enumerate(chunks):
        payload: dict[str, object] = {"event": "answer_delta", "delta": chunk}
        if do_replace and index == 0:
            payload["replace"] = True
        bridge.emit_nowait(payload)
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

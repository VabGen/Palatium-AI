# src/palatium_ai/application/agents/formatter/stream_delta.py

"""Formatter markdown SSE: text_delta (primary) + dual answer_delta (migration)."""

from __future__ import annotations

import time

from dataclasses import dataclass, field

from palatium_ai.application.agents.formatter.icon_sanitizer import (
    flush_stream_tail,
    split_stream_chunk,
)
from palatium_ai.application.services.turn_sse_bridge import TurnSseBridge, get_turn_sse_bridge
from palatium_ai.core.observability.metrics import agent_metrics
from palatium_ai.domain.policies.internal_vocabulary import InternalVocabularyPolicy


@dataclass(slots=True)
class FormatterMarkdownEmitter:
    """Emit Hybrid stream chunks; ``replace`` only on the first chunk after a worker draft.

    SSE preview keeps ``<icon name="…"/>`` (FE renders TokenIcon) and drops emoji.
    The parse buffer keeps the same mapped tokens for ``markdown_to_content_document``.

    Preview frames pass through ``InternalVocabularyPolicy`` on the way out. The final
    ``ContentDocument`` is sanitised by the parser, so an unsanitised preview would
    differ from the document that replaces it — a guaranteed visible swap at the end of
    every turn that quotes an internal field name (055).
    """

    bridge: TurnSseBridge
    replace_pending: bool
    buffer: str = field(default="", repr=False)
    _tail: str = field(default="", repr=False)
    # Held-back preview text whose trailing part may still be an internal marker.
    _preview_hold: str = field(default="", repr=False)

    @classmethod
    def bind(cls) -> FormatterMarkdownEmitter | None:
        bridge = get_turn_sse_bridge()
        if bridge is None:
            return None
        # replace:true once when Formatter replaces an already-shown worker draft.
        return cls(bridge=bridge, replace_pending=bridge.has_emitted_answer)

    def on_delta(self, chunk: str) -> None:
        if not chunk:
            return
        preview, buffered, self._tail = split_stream_chunk(chunk, self._tail)
        if buffered:
            self.buffer += buffered
        if not preview and not buffered:
            return
        # Dual-emit when preview or buffer advanced (icon-only chunks still paint).
        if preview:
            self._emit_preview(preview)

    def finish(self) -> str:
        """Flush emoji carry-tail into the parse buffer; emit any leftover preview."""
        preview, buffered = flush_stream_tail(self._tail)
        self._tail = ""
        if buffered:
            self.buffer += buffered
        if preview:
            self._emit_preview(preview)
        self._flush_preview_hold()
        return self.buffer

    def emit_fallback_prose(self, prose: str) -> None:
        """Emit worker-summary fallback before first Formatter token (Phase 2).

        No-op when the draft is already on screen (that is the normal case for a
        grounded turn, where ``researcher_node`` painted it): re-painting identical
        text is flicker, not progress (040).
        """
        text = InternalVocabularyPolicy.sanitize_text(prose).strip()
        if not text:
            return
        self.replace_pending = True  # real Formatter tokens should replace fallback
        if self.bridge.answer_already_painted(text):
            return
        replace = self.bridge.answer_replace_allowed(want_replace=True)
        self.bridge.emit_nowait({"event": "text_delta", "content": text})
        answer: dict[str, object] = {"event": "answer_delta", "delta": text, "fallback": True}
        if replace:
            answer["replace"] = True
            agent_metrics.record_sse_layout_shift(contract="legacy_markdown")
        self.bridge.emit_nowait(answer)
        self.bridge.record_answer_frame(text, replace=replace)
        if not self.bridge.sse_ttft_recorded:
            self.bridge.sse_ttft_recorded = True
            agent_metrics.record_sse_ttft(time.perf_counter() - self.bridge.started_at)
        agent_metrics.record_node_execution("formatter", "emit:fallback_stream")

    def _emit_preview(self, preview: str) -> None:
        """Hold any trailing partial internal marker, paint the safe prefix."""
        pending = self._preview_hold + preview
        cut = InternalVocabularyPolicy.safe_cut(pending)
        self._preview_hold = pending[cut:]
        if cut > 0:
            self._paint(pending[:cut])

    def _flush_preview_hold(self) -> None:
        held, self._preview_hold = self._preview_hold, ""
        if held:
            self._paint(held)

    def _paint(self, frame: str) -> None:
        """Emit one boundary-safe preview frame (text_delta + answer_delta)."""
        delta = InternalVocabularyPolicy.sanitize_text(frame)
        if not delta:
            return
        self.bridge.emit_nowait({"event": "text_delta", "content": delta})
        answer: dict[str, object] = {"event": "answer_delta", "delta": delta}
        replace = False
        if self.replace_pending:
            replace = self.bridge.answer_replace_allowed(want_replace=True)
            self.replace_pending = False
            if replace:
                answer["replace"] = True
                agent_metrics.record_sse_layout_shift(contract="legacy_markdown")
        self.bridge.emit_nowait(answer)
        self.bridge.record_answer_frame(delta, replace=replace)
        if not self.bridge.sse_ttft_recorded:
            self.bridge.sse_ttft_recorded = True
            agent_metrics.record_sse_ttft(time.perf_counter() - self.bridge.started_at)

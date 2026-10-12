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


@dataclass(slots=True)
class FormatterMarkdownEmitter:
    """Emit Hybrid stream chunks; ``replace`` only on the first chunk after a worker draft.

    SSE carries sanitised preview text (no emoji / no ``<icon/>``). The parse buffer
    keeps ``<icon name="…"/>`` tokens for ``markdown_to_content_document``.
    """

    bridge: TurnSseBridge
    replace_pending: bool
    buffer: str = field(default="", repr=False)
    _tail: str = field(default="", repr=False)

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
        # Dual-emit only when there is user-visible preview; empty preview after
        # icon-only mapping still advances buffer without flashing tokens.
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
        return self.buffer

    def emit_fallback_prose(self, prose: str) -> None:
        """Emit worker-summary fallback before first Formatter token (Phase 2)."""
        text = prose.strip()
        if not text:
            return
        self.bridge.emit_nowait({"event": "text_delta", "content": text})
        self.bridge.emit_nowait(
            {
                "event": "answer_delta",
                "delta": text,
                "replace": True,
                "fallback": True,
            }
        )
        self.replace_pending = True  # real Formatter tokens should replace fallback
        if not self.bridge.sse_ttft_recorded:
            self.bridge.sse_ttft_recorded = True
            agent_metrics.record_sse_ttft(time.perf_counter() - self.bridge.started_at)
        self.bridge.has_emitted_answer = True
        agent_metrics.record_node_execution("formatter", "emit:fallback_stream")

    def _emit_preview(self, preview: str) -> None:
        self.bridge.emit_nowait({"event": "text_delta", "content": preview})
        answer: dict[str, object] = {"event": "answer_delta", "delta": preview}
        if self.replace_pending:
            answer["replace"] = True
            self.replace_pending = False
        self.bridge.emit_nowait(answer)
        if not self.bridge.sse_ttft_recorded:
            self.bridge.sse_ttft_recorded = True
            agent_metrics.record_sse_ttft(time.perf_counter() - self.bridge.started_at)
        self.bridge.has_emitted_answer = True

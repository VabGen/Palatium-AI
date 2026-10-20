# src/palatium_ai/application/services/turn_sse_bridge.py

"""Per-turn asyncio queue for mid-graph SSE deltas (formatter token stream, W1.4)."""

from __future__ import annotations

import asyncio
import re
import time

from collections.abc import Iterator
from contextlib import contextmanager
from contextvars import ContextVar, Token
from dataclasses import dataclass, field
from typing import Any

from palatium_ai.domain.policies.types import STREAMING_CONTRACT_DEFAULT, StreamingContract


@dataclass(slots=True)
class TurnSseBridge:
    """Queue of SSE event dicts emitted from inside graph nodes."""

    queue: asyncio.Queue[dict[str, Any]] = field(default_factory=asyncio.Queue)
    # Monotonic start for SSE TTFT (first user-visible answer_delta).
    started_at: float = field(default_factory=time.perf_counter)
    has_emitted_answer: bool = False
    sse_ttft_recorded: bool = False
    # Tail of every user-visible answer_delta frame already queued: the single
    # source of truth for "what the user can currently read" (065). Bounded so a
    # long turn cannot grow it without limit (080).
    painted_answer_tail: str = ""
    # The per-turn replace budget is spent; a second reset could only re-paint
    # content the user is already reading (040: layout shift, not a feature).
    answer_replaced: bool = False
    # Which user-facing streaming contract this turn runs under. Owned here because
    # every paint goes through this bridge, so it is the only place a node can ask
    # "may I paint, and will something replace me later?" (055: one contract).
    stream_contract: StreamingContract = STREAMING_CONTRACT_DEFAULT

    async def emit(self, event: dict[str, Any]) -> None:
        """Enqueue one SSE event (non-blocking for the consumer loop)."""
        await self.queue.put(event)

    def emit_nowait(self, event: dict[str, Any]) -> None:
        """Enqueue without awaiting (formatter hot path)."""
        self.queue.put_nowait(event)

    def answer_replace_allowed(self, *, want_replace: bool) -> bool:
        """Whether this frame may reset an already-painted preview.

        Invariant: at most ONE reset per turn, and only when something was painted.
        A reset re-renders the visible answer from scratch, so every reset after the
        first is a layout shift with zero information gain (055). The one legitimate
        reset is the early worker draft handing over to the streamed Formatter answer.
        """
        return want_replace and self.has_emitted_answer and not self.answer_replaced

    def record_answer_frame(self, delta: str, *, replace: bool) -> None:
        """Track the painted preview; call once per queued answer_delta frame."""
        self.has_emitted_answer = True
        if replace:
            self.answer_replaced = True
            self.painted_answer_tail = delta
            return
        self.painted_answer_tail = (self.painted_answer_tail + delta)[-_PAINTED_TAIL_CHARS:]

    def answer_already_painted(self, text: str) -> bool:
        """True when ``text`` is already (part of) what the user reads.

        Re-emitting it is a pure layout shift: same pixels, extra flicker. Whitespace
        is collapsed because the draft travels through ``compress_worker_context``
        between the node that first painted it and the node that re-emits it.
        """
        painted = _collapse_whitespace(self.painted_answer_tail)
        key = _collapse_whitespace(text)
        return bool(key) and key in painted

    def structured_preview_active(self) -> bool:
        """True when the terminal document paints itself block-by-block.

        An intermediate worker draft must not be painted in that case: nothing will
        replace it (that is the whole point of the contract), so it would sit above
        the final answer forever. The typing indicator covers the wait (065/055).
        """
        return self.stream_contract == "structured_incremental"


#: Kept short: only the most recent paint is needed to recognise a re-emit.
_PAINTED_TAIL_CHARS = 4096
_WHITESPACE_RE = re.compile(r"\s+")


def _collapse_whitespace(text: str) -> str:
    return _WHITESPACE_RE.sub(" ", text).strip()


_current: ContextVar[TurnSseBridge | None] = ContextVar("turn_sse_bridge", default=None)


def get_turn_sse_bridge() -> TurnSseBridge | None:
    """Return SSE bridge for the active streaming turn, if any."""
    return _current.get()


@contextmanager
def turn_sse_bridge(bridge: TurnSseBridge) -> Iterator[TurnSseBridge]:
    """Bind SSE bridge for one ``process_stream`` turn."""
    token: Token[TurnSseBridge | None] = _current.set(bridge)
    try:
        yield bridge
    finally:
        _current.reset(token)

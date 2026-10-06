# src/palatium_ai/core/observability/hop_timings.py

"""Per-turn hop latency collector (ContextVar, not graph state).

Keeps checkpoint state lean while still emitting one INFO summary per turn.
"""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
from contextvars import ContextVar, Token
from dataclasses import dataclass, field


@dataclass(slots=True)
class HopTiming:
    """One graph node duration."""

    node: str
    agent: str
    duration_ms: int
    status: str | None = None


@dataclass
class HopTimingCollector:
    """Mutable list of hops for the current turn."""

    hops: list[HopTiming] = field(default_factory=list)
    budget_ms: int = 0

    def record(
        self,
        *,
        node: str,
        agent: str,
        duration_ms: int,
        status: str | None = None,
    ) -> None:
        """Записывает хоп в список."""
        self.hops.append(HopTiming(node=node, agent=agent, duration_ms=duration_ms, status=status))

    def total_ms(self) -> int:
        """Sum of recorded hop durations."""
        return sum(hop.duration_ms for hop in self.hops)

    def as_log_fields(self) -> dict[str, object]:
        """Compact fields for structlog (hop_ms map + total)."""
        by_node = {hop.node: hop.duration_ms for hop in self.hops}
        return {
            "hop_ms": by_node,
            "hop_total_ms": self.total_ms(),
            "hop_count": len(self.hops),
        }

    def budget_status(self, budget_ms: int | None = None) -> dict[str, object]:
        """Compare turn total against SLA budget; surface slowest hop."""
        resolved = budget_ms if budget_ms is not None else self.budget_ms
        fields = self.as_log_fields()
        total = self.total_ms()
        exceeded = resolved > 0 and total > resolved
        slowest_node: str | None = None
        slowest_ms = 0
        for hop in self.hops:
            if hop.duration_ms > slowest_ms:
                slowest_ms = hop.duration_ms
                slowest_node = hop.node
        return {
            **fields,
            "hop_budget_ms": resolved,
            "hop_budget_exceeded": exceeded,
            "hop_slowest_node": slowest_node,
            "hop_slowest_ms": slowest_ms,
        }


_current: ContextVar[HopTimingCollector | None] = ContextVar("hop_timings", default=None)


def get_hop_collector() -> HopTimingCollector | None:
    """Return collector for the active turn, if any."""
    return _current.get()


@contextmanager
def turn_hop_timings(*, budget_ms: int = 0) -> Iterator[HopTimingCollector]:
    """Bind a fresh collector for one IntentService turn."""
    collector = HopTimingCollector(budget_ms=budget_ms)
    token: Token[HopTimingCollector | None] = _current.set(collector)
    try:
        yield collector
    finally:
        _current.reset(token)

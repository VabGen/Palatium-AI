# src/palatium_ai/core/observability/hop_timings.py

"""Per-turn hop latency collector (ContextVar, not graph state).

Keeps checkpoint state lean while still emitting one INFO summary per turn.
"""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
from contextvars import ContextVar, Token
from dataclasses import dataclass, field
from typing import Protocol


class BudgetScaler(Protocol):
    """Port for scaling the turn hop budget; implemented by ``HopBudgetPolicy`` (domain).

    ``core`` must not import ``domain`` (rule 000), so the scaling policy is injected by
    the caller (``application/orchestration``) instead of being imported here.
    """

    def __call__(self, *, base_ms: int, strategy: str | None) -> int: ...


@dataclass(slots=True)
class HopTiming:
    """One graph node duration."""

    node: str
    agent: str
    duration_ms: int
    status: str | None = None


@dataclass(slots=True)
class ExternalIoSpan:
    """Time the turn spent waiting on an external system (not agent work)."""

    kind: str
    duration_ms: int


@dataclass
class HopTimingCollector:
    """Mutable list of hops for the current turn."""

    hops: list[HopTiming] = field(default_factory=list)
    #: Spans spent inside a node but owned by an external system (document parse/OCR,
    #: blob fetch). They are part of the turn's wall clock, but not of the agent's
    #: work: a 25 s OCR of two scans is not a slow graph, and counting it as one
    #: turned the hop SLA into an alert that fires on every attachment task.
    external_io: list[ExternalIoSpan] = field(default_factory=list)
    budget_ms: int = 0
    base_budget_ms: int = 0

    def apply_strategy_budget(self, strategy: str | None, *, scaler: BudgetScaler) -> None:
        """Recompute ``budget_ms`` as base × strategy scale, using the injected policy."""
        base = self.base_budget_ms if self.base_budget_ms > 0 else self.budget_ms
        self.budget_ms = scaler(base_ms=base, strategy=strategy)

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

    def record_external_io(self, *, kind: str, duration_ms: int) -> None:
        """Attribute a span of the current turn to an external system (see ``external_io``)."""
        if duration_ms > 0:
            self.external_io.append(ExternalIoSpan(kind=kind, duration_ms=duration_ms))

    def total_ms(self) -> int:
        """Wall clock the turn spent inside graph nodes."""
        return sum(hop.duration_ms for hop in self.hops)

    def io_ms(self) -> int:
        """Part of ``total_ms`` spent waiting on an external system."""
        return sum(span.duration_ms for span in self.external_io)

    def agent_ms(self) -> int:
        """Turn latency owned by the agents — the quantity the hop budget governs."""
        return max(0, self.total_ms() - self.io_ms())

    def as_log_fields(self) -> dict[str, object]:
        """Compact fields for structlog (hop_ms map + total + external I/O)."""
        by_node = {hop.node: hop.duration_ms for hop in self.hops}
        by_kind: dict[str, int] = {}
        for span in self.external_io:
            by_kind[span.kind] = by_kind.get(span.kind, 0) + span.duration_ms
        return {
            "hop_ms": by_node,
            "hop_total_ms": self.total_ms(),
            "hop_count": len(self.hops),
            "hop_agent_ms": self.agent_ms(),
            "hop_io_ms": self.io_ms(),
            "hop_io_ms_by_kind": by_kind,
        }

    def budget_status(self, budget_ms: int | None = None) -> dict[str, object]:
        """Compare agent work against the SLA budget; surface slowest hop.

        Two verdicts, deliberately separate: ``hop_budget_exceeded`` means the agents
        burned more than the budget (actionable — a prompt or a loop regressed), while
        ``hop_wall_over_budget`` means the turn was slow because of documented I/O
        (a fact to report, not an agent defect).
        """
        resolved = budget_ms if budget_ms is not None else self.budget_ms
        fields = self.as_log_fields()
        agent_total = self.agent_ms()
        wall_total = self.total_ms()
        exceeded = resolved > 0 and agent_total > resolved
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
            "hop_wall_over_budget": resolved > 0 and wall_total > resolved and not exceeded,
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
    collector = HopTimingCollector(budget_ms=budget_ms, base_budget_ms=budget_ms)
    token: Token[HopTimingCollector | None] = _current.set(collector)
    try:
        yield collector
    finally:
        _current.reset(token)

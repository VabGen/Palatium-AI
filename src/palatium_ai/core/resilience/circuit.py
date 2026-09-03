# src/palatium_ai/core/resilience/circuit.py

"""Generic consecutive-failure circuit breaker with half-open probe (020)."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Literal

_FAILURES_TO_OPEN = 3
_OPEN_SECONDS = 30.0

CircuitState = Literal["closed", "open", "half_open"]


@dataclass(slots=True)
class ConsecutiveFailureCircuit:
    """Mutable circuit: closed → open → half_open → closed."""

    consecutive_failures: int = 0
    open_until: float = 0.0
    failures_to_open: int = _FAILURES_TO_OPEN
    open_seconds: float = _OPEN_SECONDS
    state: CircuitState = field(default="closed", init=False)
    _probe_in_flight: bool = field(default=False, init=False, repr=False)

    def state_code(self) -> int:
        """Prometheus gauge encoding: 0=closed, 1=half_open, 2=open (040)."""
        if self.state == "half_open":
            return 1
        if self.state == "open":
            return 2
        return 0

    def _maybe_transition_from_open(self, now: float) -> None:
        if self.state == "open" and now >= self.open_until:
            self.state = "half_open"
            self._probe_in_flight = False

    def is_open(self, now: float) -> bool:
        """Return True while calls must be refused (open, or half_open probe taken)."""
        self._maybe_transition_from_open(now)
        if self.state == "closed":
            return False
        if self.state == "half_open":
            return self._probe_in_flight
        return now < self.open_until

    def allow_request(self, now: float) -> bool:
        """Acquire permission to run (handles half-open single probe)."""
        if self.is_open(now):
            return False
        if self.state == "half_open":
            self._probe_in_flight = True
        return True

    def record_success(self) -> None:
        """Reset after a successful call."""
        self.consecutive_failures = 0
        self.open_until = 0.0
        self.state = "closed"
        self._probe_in_flight = False

    def record_failure(self, now: float) -> None:
        """Record failure; re-open from half_open or count toward threshold."""
        self._probe_in_flight = False
        if self.state == "half_open":
            self.state = "open"
            self.open_until = now + self.open_seconds
            return
        self.consecutive_failures += 1
        if self.consecutive_failures >= self.failures_to_open:
            self.state = "open"
            self.open_until = now + self.open_seconds


class CircuitOpenError(RuntimeError):
    """Raised when a call is refused because the circuit is open."""

    def __init__(self, name: str, *, retry_after_seconds: float) -> None:
        self.name = name
        self.retry_after_seconds = retry_after_seconds
        super().__init__(f"Circuit open for '{name}' (retry after ~{retry_after_seconds:.0f}s)")

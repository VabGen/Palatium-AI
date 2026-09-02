# src/palatium_ai/core/resilience/circuit.py

"""Generic consecutive-failure circuit breaker (3 fails → open)."""

from __future__ import annotations

from dataclasses import dataclass

_FAILURES_TO_OPEN = 3
_OPEN_SECONDS = 30.0


@dataclass(slots=True)
class ConsecutiveFailureCircuit:
    """Mutable circuit state keyed by an external identity (server, node, …)."""

    consecutive_failures: int = 0
    open_until: float = 0.0
    failures_to_open: int = _FAILURES_TO_OPEN
    open_seconds: float = _OPEN_SECONDS

    def is_open(self, now: float) -> bool:
        """Return True while the circuit is open."""
        return now < self.open_until

    def record_success(self) -> None:
        """Reset consecutive failures after a success."""
        self.consecutive_failures = 0
        self.open_until = 0.0

    def record_failure(self, now: float) -> None:
        """Record a failure; open the circuit after the threshold."""
        self.consecutive_failures += 1
        if self.consecutive_failures >= self.failures_to_open:
            self.open_until = now + self.open_seconds


class CircuitOpenError(RuntimeError):
    """Raised when a call is refused because the circuit is open."""

    def __init__(self, name: str, *, retry_after_seconds: float) -> None:
        self.name = name
        self.retry_after_seconds = retry_after_seconds
        super().__init__(f"Circuit open for '{name}' (retry after ~{retry_after_seconds:.0f}s)")

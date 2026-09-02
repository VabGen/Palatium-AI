# src/palatium_ai/infrastructure/resilience/circuit.py

"""Backward-compatible re-export — circuit lives in core (application must not own infra deps)."""

from palatium_ai.core.resilience.circuit import CircuitOpenError, ConsecutiveFailureCircuit

__all__ = ["CircuitOpenError", "ConsecutiveFailureCircuit"]

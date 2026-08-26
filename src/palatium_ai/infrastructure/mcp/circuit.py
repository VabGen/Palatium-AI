# src/palatium_ai/infrastructure/mcp/circuit.py

"""Per-server MCP circuit: fail-fast after consecutive list/call failures."""

from __future__ import annotations

from palatium_ai.infrastructure.resilience.circuit import ConsecutiveFailureCircuit

# Backward-compatible alias used by MCPRegistry.
McpServerCircuit = ConsecutiveFailureCircuit

__all__ = ["McpServerCircuit"]

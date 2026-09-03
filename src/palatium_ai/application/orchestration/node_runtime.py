# src/palatium_ai/application/orchestration/node_runtime.py

"""Shared node runtime: circuit breaker, logging, metrics (065)."""

from __future__ import annotations

from time import perf_counter, time
from typing import TYPE_CHECKING, Any

from palatium_ai.application.orchestration.state import AgentGraphState
from palatium_ai.core.config.settings import get_settings
from palatium_ai.core.logging import get_logger
from palatium_ai.core.observability.hop_timings import get_hop_collector
from palatium_ai.core.observability.metrics import agent_metrics
from palatium_ai.core.resilience.circuit import CircuitOpenError, ConsecutiveFailureCircuit

if TYPE_CHECKING:
    from collections.abc import Awaitable, Callable

logger = get_logger(__name__)

_NODE_CIRCUITS: dict[str, ConsecutiveFailureCircuit] = {}


def node_circuit(node_name: str) -> ConsecutiveFailureCircuit:
    if node_name in _NODE_CIRCUITS:
        return _NODE_CIRCUITS[node_name]
    obs = get_settings().observability
    circuit = ConsecutiveFailureCircuit(
        failures_to_open=obs.circuit_failures_to_open,
        open_seconds=obs.circuit_open_seconds,
    )
    _NODE_CIRCUITS[node_name] = circuit
    return circuit


def reset_node_circuits_for_tests() -> None:
    """Clear agent-node circuits (unit tests only)."""
    _NODE_CIRCUITS.clear()


def agent_identity(agent: object, *, fallback: str) -> tuple[str, str]:
    config = getattr(agent, "config", None)
    name = getattr(config, "name", None)
    role = getattr(config, "role", None)
    return (
        name if isinstance(name, str) and name else fallback,
        role if isinstance(role, str) and role else fallback,
    )


def result_fields(result: object) -> dict[str, Any]:
    fields: dict[str, Any] = {}
    status = getattr(result, "status", None)
    if isinstance(status, str):
        fields["status"] = status
    confidence = getattr(result, "confidence", None)
    if isinstance(confidence, (int, float)):
        fields["confidence"] = round(float(confidence), 3)
    requires_review = getattr(result, "requires_review", None)
    if isinstance(requires_review, bool):
        fields["requires_review"] = requires_review
    error = getattr(result, "error", None)
    if isinstance(error, str) and error:
        fields["error"] = error
    return fields


async def run_logged_node(
    *,
    agent: object,
    node_name: str,
    state: AgentGraphState,
    run: Callable[[], Awaitable[tuple[AgentGraphState, object]]],
) -> AgentGraphState:
    """Run a graph node with circuit breaker, hop timings, and structured logs."""
    agent_name, agent_role = agent_identity(agent, fallback=node_name)
    task_id = state["task_id"]
    thread_id = state.get("thread_id", task_id)
    node_metric = f"{node_name}_node"
    circuit = node_circuit(node_name)
    now = time()
    if not circuit.allow_request(now):
        retry_after = max(0.0, circuit.open_until - now)
        agent_metrics.record_error(agent_role, "CircuitOpenError")
        agent_metrics.record_circuit_state(node_name, circuit.state_code())
        logger.warning(
            "agent.node.circuit_open",
            agent=agent_name,
            agent_role=agent_role,
            node=node_name,
            task_id=task_id,
            thread_id=thread_id,
            retry_after_seconds=round(retry_after, 1),
        )
        raise CircuitOpenError(node_name, retry_after_seconds=retry_after)

    logger.debug(
        "agent.node.start",
        agent=agent_name,
        agent_role=agent_role,
        node=node_name,
        task_id=task_id,
        thread_id=thread_id,
    )
    started = perf_counter()
    try:
        update, result = await run()
    except Exception as exc:
        duration_ms = round((perf_counter() - started) * 1000)
        circuit.record_failure(time())
        agent_metrics.record_circuit_state(node_name, circuit.state_code())
        agent_metrics.record_node_execution(agent_role, node_metric, duration_seconds=duration_ms / 1000.0)
        agent_metrics.record_error(agent_role, type(exc).__name__)
        hop = get_hop_collector()
        if hop is not None:
            hop.record(node=node_name, agent=agent_name, duration_ms=duration_ms, status="error")
        logger.warning(
            "agent.node.error",
            agent=agent_name,
            agent_role=agent_role,
            node=node_name,
            task_id=task_id,
            thread_id=thread_id,
            duration_ms=duration_ms,
            error=str(exc),
            circuit_failures=circuit.consecutive_failures,
        )
        raise
    circuit.record_success()
    agent_metrics.record_circuit_state(node_name, circuit.state_code())
    duration_ms = round((perf_counter() - started) * 1000)
    fields = result_fields(result)
    agent_metrics.record_node_execution(agent_role, node_metric, duration_seconds=duration_ms / 1000.0)
    hop = get_hop_collector()
    if hop is not None:
        status = fields.get("status")
        hop.record(
            node=node_name,
            agent=agent_name,
            duration_ms=duration_ms,
            status=status if isinstance(status, str) else None,
        )
    logger.debug(
        "agent.node.end",
        agent=agent_name,
        agent_role=agent_role,
        node=node_name,
        task_id=task_id,
        thread_id=thread_id,
        duration_ms=duration_ms,
        **fields,
    )
    return update

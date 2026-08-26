# src/palatium_ai/core/observability/metrics.py

"""In-process метрики агентов (Prometheus-совместимые имена)."""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass, field
from threading import Lock


class _NoopMetric:
    """No-op Prometheus metric implementation (dev/test fallback)."""

    def labels(self, *_args: object, **_kwargs: object) -> _NoopMetric:
        return self

    def inc(self, *_args: object, **_kwargs: object) -> None:
        return None

    def observe(self, *_args: object, **_kwargs: object) -> None:
        return None


try:  # pragma: no cover - optional dependency
    from prometheus_client import (
        Counter as _PromCounter,
        Histogram as _PromHistogram,
    )

    _agent_request_duration_seconds: _PromHistogram | _NoopMetric = _PromHistogram(
        "agent_request_duration_seconds",
        "Agent node execution duration (seconds).",
        ["agent_type", "node_name"],
    )
    _agent_errors_total: _PromCounter | _NoopMetric = _PromCounter(
        "agent_errors_total",
        "Agent errors total.",
        ["agent_type", "error_type"],
    )
    _agent_human_escalation_total: _PromCounter | _NoopMetric = _PromCounter(
        "agent_human_escalation_total",
        "Human escalation total.",
        ["reason"],
    )
    _agent_hitl_deny_total: _PromCounter | _NoopMetric = _PromCounter(
        "agent_hitl_deny_total",
        "HITL deny-path total (forge, conflict, expired, forbidden, …).",
        ["reason"],
    )
    _agent_turn_hop_budget_exceeded_total: _PromCounter | _NoopMetric = _PromCounter(
        "agent_turn_hop_budget_exceeded_total",
        "Turns exceeding configured hop latency budget.",
    )
    _agent_token_usage_total: _PromCounter | _NoopMetric = _PromCounter(
        "agent_token_usage_total",
        "LLM token usage total.",
        ["model", "agent_type", "direction"],
    )
    _agent_cost_usd: _PromCounter | _NoopMetric = _PromCounter(
        "agent_cost_usd",
        "Estimated LLM cost in USD.",
        ["task_type", "model"],
    )
except ImportError:  # pragma: no cover - fallback
    _agent_request_duration_seconds = _NoopMetric()
    _agent_errors_total = _NoopMetric()
    _agent_human_escalation_total = _NoopMetric()
    _agent_hitl_deny_total = _NoopMetric()
    _agent_turn_hop_budget_exceeded_total = _NoopMetric()
    _agent_token_usage_total = _NoopMetric()
    _agent_cost_usd = _NoopMetric()


@dataclass
class AgentMetrics:
    """Потокобезопасный сборщик метрик агентов."""

    _lock: Lock = field(default_factory=Lock, repr=False)
    _node_executions: dict[tuple[str, str], int] = field(default_factory=lambda: defaultdict(int), repr=False)
    _errors: dict[tuple[str, str], int] = field(default_factory=lambda: defaultdict(int), repr=False)
    _escalations: dict[str, int] = field(default_factory=lambda: defaultdict(int), repr=False)
    _hitl_denies: dict[str, int] = field(default_factory=lambda: defaultdict(int), repr=False)

    def record_node_execution(
        self,
        agent_type: str,
        node_name: str,
        *,
        duration_seconds: float = 0.0,
    ) -> None:
        """agent_request_duration_seconds — вызов узла + реальная длительность."""
        with self._lock:
            self._node_executions[(agent_type, node_name)] += 1
        safe_duration = max(0.0, float(duration_seconds))
        _agent_request_duration_seconds.labels(agent_type=agent_type, node_name=node_name).observe(safe_duration)

    def record_error(self, agent_type: str, error_type: str) -> None:
        """agent_errors_total."""
        with self._lock:
            self._errors[(agent_type, error_type)] += 1
        _agent_errors_total.labels(agent_type=agent_type, error_type=error_type).inc()

    def record_human_escalation(self, reason: str) -> None:
        """agent_human_escalation_total."""
        with self._lock:
            self._escalations[reason] += 1
        _agent_human_escalation_total.labels(reason=reason).inc()

    def record_hitl_deny(self, reason: str) -> None:
        """Increment agent_hitl_deny_total (forge / conflict / expired / forbidden)."""
        safe = (reason or "unknown").strip()[:64] or "unknown"
        with self._lock:
            self._hitl_denies[safe] += 1
        _agent_hitl_deny_total.labels(reason=safe).inc()

    def hitl_deny_count(self, reason: str) -> int:
        """Return deny-path count for tests."""
        with self._lock:
            return self._hitl_denies[reason]

    def record_turn_hop_budget_exceeded(self) -> None:
        """agent_turn_hop_budget_exceeded_total."""
        _agent_turn_hop_budget_exceeded_total.inc()

    def record_token_usage(
        self,
        *,
        agent_type: str,
        model: str,
        prompt_tokens: int,
        completion_tokens: int,
        cost_usd: float = 0.0,
    ) -> None:
        """agent_token_usage_total + agent_cost_usd when estimate available."""
        if prompt_tokens > 0:
            _agent_token_usage_total.labels(
                model=model,
                agent_type=agent_type,
                direction="prompt",
            ).inc(prompt_tokens)
        if completion_tokens > 0:
            _agent_token_usage_total.labels(
                model=model,
                agent_type=agent_type,
                direction="completion",
            ).inc(completion_tokens)
        if cost_usd > 0.0:
            _agent_cost_usd.labels(task_type=agent_type, model=model).inc(cost_usd)

    def node_execution_count(self, agent_type: str, node_name: str) -> int:
        """Возвращает число вызовов узла (для тестов)."""
        with self._lock:
            return self._node_executions[(agent_type, node_name)]

    def error_count(self, agent_type: str, error_type: str) -> int:
        """Возвращает число ошибок (для тестов)."""
        with self._lock:
            return self._errors[(agent_type, error_type)]


agent_metrics = AgentMetrics()

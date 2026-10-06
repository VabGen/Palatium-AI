# src/palatium_ai/core/observability/metrics.py

"""Prometheus metrics registry (040) — palatium_* names only."""

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

    def set(self, *_args: object, **_kwargs: object) -> None:
        return None


try:  # pragma: no cover - optional dependency
    from prometheus_client import (
        Counter as _PromCounter,
        Gauge as _PromGauge,
        Histogram as _PromHistogram,
    )

    _palatium_agent_request_duration_seconds: _PromHistogram | _NoopMetric = _PromHistogram(
        "palatium_agent_request_duration_seconds",
        "Agent node execution duration (seconds).",
        ["agent_type", "node_name"],
    )
    _palatium_agent_errors_total: _PromCounter | _NoopMetric = _PromCounter(
        "palatium_agent_errors_total",
        "Agent errors total.",
        ["agent_type", "error_type"],
    )
    _palatium_agent_human_escalation_total: _PromCounter | _NoopMetric = _PromCounter(
        "palatium_agent_human_escalation_total",
        "Human escalation total.",
        ["reason"],
    )
    _palatium_hitl_deny_total: _PromCounter | _NoopMetric = _PromCounter(
        "palatium_hitl_deny_total",
        "HITL deny-path total (forge, conflict, expired, forbidden, …).",
        ["reason"],
    )
    _palatium_hitl_card_replay_rejected_total: _PromCounter | _NoopMetric = _PromCounter(
        "palatium_hitl_card_replay_rejected_total",
        "HITL card replay rejected total.",
    )
    _palatium_turn_hop_budget_exceeded_total: _PromCounter | _NoopMetric = _PromCounter(
        "palatium_turn_hop_budget_exceeded_total",
        "Turns exceeding configured hop latency budget.",
    )
    _palatium_agent_token_usage_total: _PromCounter | _NoopMetric = _PromCounter(
        "palatium_agent_token_usage_total",
        "LLM token usage total.",
        ["model", "agent_type", "direction"],
    )
    _palatium_agent_cost_usd_total: _PromCounter | _NoopMetric = _PromCounter(
        "palatium_agent_cost_usd_total",
        "Estimated LLM cost in USD.",
        ["model", "direction"],
    )
    _palatium_rbac_denied_total: _PromCounter | _NoopMetric = _PromCounter(
        "palatium_rbac_denied_total",
        "RBAC tool denials total.",
        ["agent_type", "tool_name"],
    )
    _palatium_circuit_breaker_state: _PromGauge | _NoopMetric = _PromGauge(
        "palatium_circuit_breaker_state",
        "Circuit breaker state (0=closed, 1=half_open, 2=open).",
        ["target"],
    )
    _palatium_memory_query_duration_seconds: _PromHistogram | _NoopMetric = _PromHistogram(
        "palatium_memory_query_duration_seconds",
        "Memory query duration (seconds).",
    )
    _palatium_memory_entry_size_bytes: _PromHistogram | _NoopMetric = _PromHistogram(
        "palatium_memory_entry_size_bytes",
        "Memory entry size in bytes.",
        ["memory_type"],
    )
    _palatium_context_tokens_used: _PromCounter | _NoopMetric = _PromCounter(
        "palatium_context_tokens_used",
        "Context tokens delivered to agents.",
        ["agent_type"],
    )
    _palatium_audit_write_failures_total: _PromCounter | _NoopMetric = _PromCounter(
        "palatium_audit_write_failures_total",
        "Audit chain write failures (degraded path).",
    )
    _palatium_secret_redactions_total: _PromCounter | _NoopMetric = _PromCounter(
        "palatium_secret_redactions_total",
        "Secret-shaped values masked instead of forwarded (020).",
        ["agent_type", "stage"],
    )
    _palatium_attachment_parse_total: _PromCounter | _NoopMetric = _PromCounter(
        "palatium_attachment_parse_total",
        "Attachment parse outcomes by extraction source (closed label sets).",
        ["extraction_source", "media_kind"],
    )
    _palatium_turn_duration_seconds: _PromHistogram | _NoopMetric = _PromHistogram(
        "palatium_turn_duration_seconds",
        "End-to-end intent process turn duration (seconds).",
        ["task_kind", "strategy"],
    )
    _palatium_llm_ttft_seconds: _PromHistogram | _NoopMetric = _PromHistogram(
        "palatium_llm_ttft_seconds",
        "Time to first LLM stream token (seconds).",
    )
    _palatium_cache_hit_total: _PromCounter | _NoopMetric = _PromCounter(
        "palatium_cache_hit_total",
        "Application cache hits by layer.",
        ["cache_layer"],
    )
    _palatium_cache_miss_total: _PromCounter | _NoopMetric = _PromCounter(
        "palatium_cache_miss_total",
        "Application cache misses by layer.",
        ["cache_layer"],
    )
except ImportError:  # pragma: no cover - fallback
    _palatium_agent_request_duration_seconds = _NoopMetric()
    _palatium_agent_errors_total = _NoopMetric()
    _palatium_agent_human_escalation_total = _NoopMetric()
    _palatium_hitl_deny_total = _NoopMetric()
    _palatium_hitl_card_replay_rejected_total = _NoopMetric()
    _palatium_turn_hop_budget_exceeded_total = _NoopMetric()
    _palatium_agent_token_usage_total = _NoopMetric()
    _palatium_agent_cost_usd_total = _NoopMetric()
    _palatium_rbac_denied_total = _NoopMetric()
    _palatium_circuit_breaker_state = _NoopMetric()
    _palatium_memory_query_duration_seconds = _NoopMetric()
    _palatium_memory_entry_size_bytes = _NoopMetric()
    _palatium_context_tokens_used = _NoopMetric()
    _palatium_audit_write_failures_total = _NoopMetric()
    _palatium_secret_redactions_total = _NoopMetric()
    _palatium_attachment_parse_total = _NoopMetric()
    _palatium_turn_duration_seconds = _NoopMetric()
    _palatium_llm_ttft_seconds = _NoopMetric()
    _palatium_cache_hit_total = _NoopMetric()
    _palatium_cache_miss_total = _NoopMetric()


@dataclass
class AgentMetrics:
    """Потокобезопасный сборщик метрик агентов."""

    _lock: Lock = field(default_factory=Lock, repr=False)
    _node_executions: dict[tuple[str, str], int] = field(default_factory=lambda: defaultdict(int), repr=False)
    _errors: dict[tuple[str, str], int] = field(default_factory=lambda: defaultdict(int), repr=False)
    _escalations: dict[str, int] = field(default_factory=lambda: defaultdict(int), repr=False)
    _hitl_denies: dict[str, int] = field(default_factory=lambda: defaultdict(int), repr=False)
    _rbac_denies: dict[tuple[str, str], int] = field(default_factory=lambda: defaultdict(int), repr=False)
    _context_tokens: dict[str, int] = field(default_factory=lambda: defaultdict(int), repr=False)
    _secret_redactions: dict[tuple[str, str], int] = field(default_factory=lambda: defaultdict(int), repr=False)
    _attachment_parses: dict[tuple[str, str], int] = field(default_factory=lambda: defaultdict(int), repr=False)

    def record_node_execution(
        self,
        agent_type: str,
        node_name: str,
        *,
        duration_seconds: float = 0.0,
    ) -> None:
        with self._lock:
            self._node_executions[(agent_type, node_name)] += 1
        safe_duration = max(0.0, float(duration_seconds))
        _palatium_agent_request_duration_seconds.labels(agent_type=agent_type, node_name=node_name).observe(
            safe_duration
        )

    def record_error(self, agent_type: str, error_type: str) -> None:
        with self._lock:
            self._errors[(agent_type, error_type)] += 1
        _palatium_agent_errors_total.labels(agent_type=agent_type, error_type=error_type).inc()

    def record_human_escalation(self, reason: str) -> None:
        with self._lock:
            self._escalations[reason] += 1
        _palatium_agent_human_escalation_total.labels(reason=reason).inc()

    def record_hitl_deny(self, reason: str) -> None:
        safe = (reason or "unknown").strip()[:64] or "unknown"
        with self._lock:
            self._hitl_denies[safe] += 1
        _palatium_hitl_deny_total.labels(reason=safe).inc()

    def record_hitl_replay_rejected(self) -> None:
        _palatium_hitl_card_replay_rejected_total.inc()

    def record_rbac_denied(self, agent_type: str, tool_name: str) -> None:
        safe_type = (agent_type or "unknown").strip()[:64] or "unknown"
        safe_tool = (tool_name or "unknown").strip()[:128] or "unknown"
        with self._lock:
            self._rbac_denies[(safe_type, safe_tool)] += 1
        _palatium_rbac_denied_total.labels(agent_type=safe_type, tool_name=safe_tool).inc()

    def rbac_denied_count(self, agent_type: str, tool_name: str) -> int:
        with self._lock:
            return self._rbac_denies[(agent_type, tool_name)]

    def hitl_deny_count(self, reason: str) -> int:
        with self._lock:
            return self._hitl_denies[reason]

    def record_turn_hop_budget_exceeded(self) -> None:
        _palatium_turn_hop_budget_exceeded_total.inc()

    def record_token_usage(
        self,
        *,
        agent_type: str,
        model: str,
        prompt_tokens: int,
        completion_tokens: int,
        cost_usd: float = 0.0,
    ) -> None:
        if prompt_tokens > 0:
            _palatium_agent_token_usage_total.labels(
                model=model,
                agent_type=agent_type,
                direction="prompt",
            ).inc(prompt_tokens)
        if completion_tokens > 0:
            _palatium_agent_token_usage_total.labels(
                model=model,
                agent_type=agent_type,
                direction="completion",
            ).inc(completion_tokens)
        if cost_usd > 0.0:
            _palatium_agent_cost_usd_total.labels(model=model, direction="llm").inc(cost_usd)

    def record_context_tokens(self, agent_type: str, tokens: int) -> None:
        safe = (agent_type or "unknown").strip()[:64] or "unknown"
        with self._lock:
            self._context_tokens[safe] += tokens
        _palatium_context_tokens_used.labels(agent_type=safe).inc(tokens)

    def record_circuit_state(self, target: str, state_code: int) -> None:
        safe = (target or "unknown").strip()[:64] or "unknown"
        _palatium_circuit_breaker_state.labels(target=safe).set(state_code)

    def record_audit_write_failure(self) -> None:
        _palatium_audit_write_failures_total.inc()

    def record_secret_redaction(self, *, agent_type: str, stage: str) -> None:
        """Count a value masked before it could reach a model (020)."""
        safe_type = (agent_type or "unknown").strip()[:64] or "unknown"
        safe_stage = (stage or "unknown").strip()[:64] or "unknown"
        with self._lock:
            self._secret_redactions[(safe_type, safe_stage)] += 1
        _palatium_secret_redactions_total.labels(agent_type=safe_type, stage=safe_stage).inc()

    def secret_redaction_count(self, agent_type: str, stage: str) -> int:
        with self._lock:
            return self._secret_redactions[(agent_type, stage)]

    def record_attachment_parse(self, *, extraction_source: str, media_kind: str) -> None:
        """Count a successful parse by provenance (closed label vocabularies)."""
        safe_source = (extraction_source or "none").strip()[:32] or "none"
        safe_kind = (media_kind or "other").strip()[:32] or "other"
        with self._lock:
            self._attachment_parses[(safe_source, safe_kind)] += 1
        _palatium_attachment_parse_total.labels(
            extraction_source=safe_source,
            media_kind=safe_kind,
        ).inc()

    def attachment_parse_count(self, extraction_source: str, media_kind: str) -> int:
        with self._lock:
            return self._attachment_parses[(extraction_source, media_kind)]

    def record_memory_query_duration(self, duration_seconds: float) -> None:
        _palatium_memory_query_duration_seconds.observe(max(0.0, duration_seconds))

    def record_memory_entry_size(self, *, memory_type: str, size_bytes: int) -> None:
        safe_type = (memory_type or "unknown").strip()[:32] or "unknown"
        _palatium_memory_entry_size_bytes.labels(memory_type=safe_type).observe(max(0, size_bytes))

    def record_turn_duration(
        self,
        *,
        task_kind: str,
        strategy: str,
        duration_seconds: float,
    ) -> None:
        kind = (task_kind or "unknown").strip()[:64] or "unknown"
        strat = (strategy or "unknown").strip()[:64] or "unknown"
        _palatium_turn_duration_seconds.labels(task_kind=kind, strategy=strat).observe(
            max(0.0, float(duration_seconds))
        )

    def record_llm_ttft(self, duration_seconds: float) -> None:
        _palatium_llm_ttft_seconds.observe(max(0.0, float(duration_seconds)))

    def record_cache_hit(self, *, cache_layer: str) -> None:
        layer = (cache_layer or "unknown").strip()[:32] or "unknown"
        _palatium_cache_hit_total.labels(cache_layer=layer).inc()

    def record_cache_miss(self, *, cache_layer: str) -> None:
        layer = (cache_layer or "unknown").strip()[:32] or "unknown"
        _palatium_cache_miss_total.labels(cache_layer=layer).inc()

    def node_execution_count(self, agent_type: str, node_name: str) -> int:
        with self._lock:
            return self._node_executions[(agent_type, node_name)]

    def error_count(self, agent_type: str, error_type: str) -> int:
        with self._lock:
            return self._errors[(agent_type, error_type)]

    def context_tokens_count(self, agent_type: str) -> int:
        with self._lock:
            return self._context_tokens[agent_type]


agent_metrics = AgentMetrics()

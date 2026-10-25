# src/palatium_ai/core/observability/metrics.py

"""Prometheus metrics registry (040) — palatium_* names only."""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass, field
from threading import Lock
from typing import TYPE_CHECKING, Final

if TYPE_CHECKING:
    from palatium_ai.domain.policies.types import (
        FormatterGenerationPath,
        FormatterSchemaOutcome,
    )

# Adaptive Grounding latency histogram — custom buckets (pre-flip hardening).
GROUNDING_LATENCY_BUCKETS: Final[tuple[float, ...]] = (
    0.1,
    0.25,
    0.5,
    1.0,
    2.0,
    5.0,
    10.0,
    20.0,
    40.0,
    60.0,
)


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
    _palatium_llm_cost_missing_total: _PromCounter | _NoopMetric = _PromCounter(
        "palatium_llm_cost_missing_total",
        "LLM completions with tokens but no resolvable USD cost (gateway absent).",
        ["reason"],
    )
    _palatium_llm_fallback_total: _PromCounter | _NoopMetric = _PromCounter(
        "palatium_llm_fallback_total",
        "LLM calls that failed over from primary to another provider in the chain.",
        ["to_provider"],
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
    _palatium_memory_extract_queue_depth: _PromGauge | _NoopMetric = _PromGauge(
        "palatium_memory_extract_queue_depth",
        "Pending+running durable extract jobs.",
    )
    _palatium_memory_extract_queue_lag_seconds: _PromGauge | _NoopMetric = _PromGauge(
        "palatium_memory_extract_queue_lag_seconds",
        "Age of oldest pending extract job (seconds).",
    )
    _palatium_memory_extract_dead_letter_total: _PromGauge | _NoopMetric = _PromGauge(
        "palatium_memory_extract_dead_letter_total",
        "Extract jobs in dead-letter status.",
    )
    _palatium_memory_extract_enqueue_refused_total: _PromCounter | _NoopMetric = _PromCounter(
        "palatium_memory_extract_enqueue_refused_total",
        "Extract enqueues refused by a capacity ceiling (M3 E7).",
        ["reason"],
    )
    _palatium_memory_recall_at_k: _PromGauge | _NoopMetric = _PromGauge(
        "palatium_memory_recall_at_k",
        "Offline eval Recall@k (Pushgateway / nightly); not runtime hit-rate (040 / M7).",
        ["k"],
    )
    # Not a failure: the policy decided this turn has nothing recallable (060/080).
    # Separate from *_enqueue_refused_total, which means "wanted to, capacity said no".
    _palatium_memory_extract_skipped_total: _PromCounter | _NoopMetric = _PromCounter(
        "palatium_memory_extract_skipped_total",
        "Extract jobs not enqueued because the turn carries nothing recallable.",
        ["reason"],
    )
    _palatium_memory_promote_errors_total: _PromCounter | _NoopMetric = _PromCounter(
        "palatium_memory_promote_errors_total",
        "Medium→graph promote batch failures.",
        ["error_type"],
    )
    # A blocked PII supersede is *not* an error: the batch did the right thing. It is a
    # durable human decision nobody has requested yet (M5 audit F3), so it needs its own
    # series — counting it as an error would keep the error alert firing forever.
    _palatium_memory_promote_blocked_pii_total: _PromCounter | _NoopMetric = _PromCounter(
        "palatium_memory_promote_blocked_pii_total",
        "Promote candidates held back because a PII fact would be silently flipped.",
    )
    _palatium_memory_recall_source_total: _PromCounter | _NoopMetric = _PromCounter(
        "palatium_memory_recall_source_total",
        "Hot-path memory Select outcomes by source (Super Brain SB0).",
        ["source"],
    )
    _palatium_attachment_sticky_total: _PromCounter | _NoopMetric = _PromCounter(
        "palatium_attachment_sticky_total",
        "Sticky attachment resolve actions (explicit/skip/rehydrate/clear).",
        ["action"],
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
    _palatium_pii_detected_total: _PromCounter | _NoopMetric = _PromCounter(
        "palatium_pii_detected_total",
        "PII spans detected by kind and boundary profile (020).",
        ["kind", "profile"],
    )
    _palatium_constitution_violation_total: _PromCounter | _NoopMetric = _PromCounter(
        "palatium_constitution_violation_total",
        "Answer-constitution violations by article and origin (deterministic|judge).",
        ["principle", "source"],
    )
    _palatium_attachment_parse_total: _PromCounter | _NoopMetric = _PromCounter(
        "palatium_attachment_parse_total",
        "Attachment parse outcomes by extraction source (closed label sets).",
        ["extraction_source", "media_kind"],
    )
    _palatium_attachment_read_total: _PromCounter | _NoopMetric = _PromCounter(
        "palatium_attachment_read_total",
        "On-demand attachment reads (platform.read_attachment).",
        ["kind", "ocr_applied", "ocr_engine", "ocr_cached"],
    )
    # Every image that could have been sent to a vision model: allowed or refused with
    # a typed reason. A silent drop would look like "the model ignored my picture" (040).
    _palatium_vision_image_total: _PromCounter | _NoopMetric = _PromCounter(
        "palatium_vision_image_total",
        "Chat image parts by admission outcome (closed label sets, ADR 0007).",
        ["outcome", "reason"],
    )
    # Any non-zero rate means bytes were silently replaced with U+FFFD on a decode
    # fallback; the extracted text may differ from the file. Watch, not a knob (040).
    _palatium_utf8_decode_failures_total: _PromCounter | _NoopMetric = _PromCounter(
        "palatium_utf8_decode_failures_total",
        "Text decodes that fell back to errors=replace (lossy).",
        ["kind"],
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
    _palatium_sse_ttft_seconds: _PromHistogram | _NoopMetric = _PromHistogram(
        "palatium_sse_ttft_seconds",
        "Time to first user-visible answer_delta on the SSE turn (seconds).",
    )
    # Structured preview: submit → first ``block_delta``. Separate from TTFT because
    # the typed preview can start later than prose (the first element must close) and
    # a regression here is invisible in ``palatium_sse_ttft_seconds`` (040).
    _palatium_sse_first_block_seconds: _PromHistogram | _NoopMetric = _PromHistogram(
        "palatium_sse_first_block_seconds",
        "Time to first typed block_delta on the SSE turn (seconds).",
    )
    # Any non-zero rate is a bug, not a tuning knob: it means a frame we already
    # painted was overwritten (layout shift). Alert on increase(...) > 0 (040).
    _palatium_sse_layout_shift_total: _PromCounter | _NoopMetric = _PromCounter(
        "palatium_sse_layout_shift_total",
        "SSE replace/replace-pending frames that overwrite already-shown content.",
        ["contract"],
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
    _palatium_grounding_mode_total: _PromCounter | _NoopMetric = _PromCounter(
        "palatium_grounding_mode_total",
        "Turns classified by Adaptive Grounding mode.",
        ["mode"],
    )
    _palatium_grounding_degraded_total: _PromCounter | _NoopMetric = _PromCounter(
        "palatium_grounding_degraded_total",
        "Empty retrieval degraded to parametric LLM (optional grounding).",
        ["mode"],
    )
    _palatium_grounding_required_empty_total: _PromCounter | _NoopMetric = _PromCounter(
        "palatium_grounding_required_empty_total",
        "Required grounding with empty retrieval (clarification path).",
    )
    _palatium_grounding_satisfied_total: _PromCounter | _NoopMetric = _PromCounter(
        "palatium_grounding_satisfied_total",
        "Retrieval satisfied Adaptive Grounding (sources present).",
        ["mode"],
    )
    _palatium_grounding_flag_off_total: _PromCounter | _NoopMetric = _PromCounter(
        "palatium_grounding_flag_off_total",
        "Empty retrieval took Adaptive Grounding OFF stub path.",
    )
    _palatium_grounding_latency_seconds: _PromHistogram | _NoopMetric = _PromHistogram(
        "palatium_grounding_latency_seconds",
        "Adaptive Grounding empty-path handling latency (degrade or clarify).",
        ["mode", "degraded"],
        buckets=GROUNDING_LATENCY_BUCKETS,
    )
    _palatium_grounding_rollout_total: _PromCounter | _NoopMetric = _PromCounter(
        "palatium_grounding_rollout_total",
        "Hits per Adaptive Grounding sticky-rollout decision.",
        ["enabled"],
    )
    _palatium_grounding_hallucination_total: _PromCounter | _NoopMetric = _PromCounter(
        "palatium_grounding_hallucination_total",
        "Sampled hallucination detections on degraded responses.",
    )
    _palatium_grounding_judge_runs_total: _PromCounter | _NoopMetric = _PromCounter(
        "palatium_grounding_judge_runs_total",
        "LLM-judge invocations for grounding (sampled).",
    )
    _palatium_grounding_judge_failed_total: _PromCounter | _NoopMetric = _PromCounter(
        "palatium_grounding_judge_failed_total",
        "Grounding LLM-judge failures (fire-and-forget; quality signal unreliable).",
    )
    # Decomposed judge (W4): one histogram with a dimension label rather than four
    # metrics — the axes are values of one measurement, not four different facts (040).
    _palatium_judge_score: _PromHistogram | _NoopMetric = _PromHistogram(
        "palatium_judge_score",
        "LLM-judge score per decomposed dimension (W4).",
        ["dimension"],
    )
    # A failed call leaves an axis unmeasured; the verdict must then say "review",
    # never "pass" — so failures are counted instead of logged away.
    _palatium_judge_failed_total: _PromCounter | _NoopMetric = _PromCounter(
        "palatium_judge_failed_total",
        "Decomposed judge calls that produced no score, by dimension.",
        ["dimension"],
    )
    _palatium_grounding_clarification_total: _PromCounter | _NoopMetric = _PromCounter(
        "palatium_grounding_clarification_total",
        "Clarification responses emitted (hash8 + length bucket; never raw query).",
        ["query_hash", "len_bucket"],
    )
    _palatium_transform_total: _PromCounter | _NoopMetric = _PromCounter(
        "palatium_transform_total",
        "Requested prior-content transformation kind (closed label set).",
        ["kind"],
    )
    _palatium_response_shape_total: _PromCounter | _NoopMetric = _PromCounter(
        "palatium_response_shape_total",
        "Requested answer-body shape and its compliance outcome (closed label sets).",
        ["shape", "outcome"],
    )
    # Deterministic lint is the only signal for defects that are valid per schema but
    # wrong for the user (repeated prose, dangling [n], markdown residue). Both labels
    # are closed sets owned by ``domain/content/lint``; the counter never blocks a turn.
    _palatium_content_lint_findings_total: _PromCounter | _NoopMetric = _PromCounter(
        "palatium_content_lint_findings_total",
        "Deterministic ContentDocument lint findings by rule and severity.",
        ["rule", "severity"],
    )
    # Schema validity, content lint and judge score answer three different questions
    # (prompt/model vs business rules vs meaning) and must never be averaged together.
    # This counter owns the first one; ``unsupported`` stays out of its ratio (040).
    _palatium_formatter_schema_total: _PromCounter | _NoopMetric = _PromCounter(
        "palatium_formatter_schema_total",
        "Formatter generation attempts by contract and schema verdict.",
        ["path", "outcome"],
    )
    # Denominator = every citation the provider emitted; numerator = outcome
    # "resolved". "unanchored" means the model attributed text it never wrote — a
    # grounding signal, not a rendering detail (040, W3a).
    _palatium_citation_resolution_total: _PromCounter | _NoopMetric = _PromCounter(
        "palatium_citation_resolution_total",
        "Provider citations by anchor and resolution outcome (emitted vs resolved).",
        ["anchor", "outcome"],
    )
    # Denominator = every highlight request, failures included: a rate that improves
    # by refusing to answer hard quotes measures nothing (040, W3b-2).
    _palatium_citation_highlight_total: _PromCounter | _NoopMetric = _PromCounter(
        "palatium_citation_highlight_total",
        "Source-highlight requests by locate outcome.",
        ["outcome"],
    )
    _palatium_answer_writer_total: _PromCounter | _NoopMetric = _PromCounter(
        "palatium_answer_writer_total",
        "Turns by resolved answer writer (single-writer contract).",
        ["owner", "reason"],
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
    _palatium_llm_cost_missing_total = _NoopMetric()
    _palatium_llm_fallback_total = _NoopMetric()
    _palatium_rbac_denied_total = _NoopMetric()
    _palatium_circuit_breaker_state = _NoopMetric()
    _palatium_memory_query_duration_seconds = _NoopMetric()
    _palatium_memory_entry_size_bytes = _NoopMetric()
    _palatium_memory_extract_queue_depth = _NoopMetric()
    _palatium_memory_extract_queue_lag_seconds = _NoopMetric()
    _palatium_memory_extract_dead_letter_total = _NoopMetric()
    _palatium_memory_extract_enqueue_refused_total = _NoopMetric()
    _palatium_memory_extract_skipped_total = _NoopMetric()
    _palatium_memory_recall_at_k = _NoopMetric()
    _palatium_memory_promote_errors_total = _NoopMetric()
    _palatium_memory_promote_blocked_pii_total = _NoopMetric()
    _palatium_memory_recall_source_total = _NoopMetric()
    _palatium_attachment_sticky_total = _NoopMetric()
    _palatium_context_tokens_used = _NoopMetric()
    _palatium_audit_write_failures_total = _NoopMetric()
    _palatium_secret_redactions_total = _NoopMetric()
    _palatium_pii_detected_total = _NoopMetric()
    _palatium_constitution_violation_total = _NoopMetric()
    _palatium_attachment_parse_total = _NoopMetric()
    _palatium_attachment_read_total = _NoopMetric()
    _palatium_vision_image_total = _NoopMetric()
    _palatium_utf8_decode_failures_total = _NoopMetric()
    _palatium_turn_duration_seconds = _NoopMetric()
    _palatium_llm_ttft_seconds = _NoopMetric()
    _palatium_sse_ttft_seconds = _NoopMetric()
    _palatium_sse_first_block_seconds = _NoopMetric()
    _palatium_sse_layout_shift_total = _NoopMetric()
    _palatium_cache_hit_total = _NoopMetric()
    _palatium_cache_miss_total = _NoopMetric()
    _palatium_grounding_mode_total = _NoopMetric()
    _palatium_grounding_degraded_total = _NoopMetric()
    _palatium_grounding_required_empty_total = _NoopMetric()
    _palatium_grounding_satisfied_total = _NoopMetric()
    _palatium_grounding_flag_off_total = _NoopMetric()
    _palatium_grounding_latency_seconds = _NoopMetric()
    _palatium_grounding_rollout_total = _NoopMetric()
    _palatium_grounding_hallucination_total = _NoopMetric()
    _palatium_grounding_judge_runs_total = _NoopMetric()
    _palatium_judge_score = _NoopMetric()
    _palatium_judge_failed_total = _NoopMetric()
    _palatium_grounding_judge_failed_total = _NoopMetric()
    _palatium_grounding_clarification_total = _NoopMetric()
    _palatium_transform_total = _NoopMetric()
    _palatium_response_shape_total = _NoopMetric()
    _palatium_answer_writer_total = _NoopMetric()
    _palatium_content_lint_findings_total = _NoopMetric()
    _palatium_citation_resolution_total = _NoopMetric()
    _palatium_citation_highlight_total = _NoopMetric()
    _palatium_formatter_schema_total = _NoopMetric()


@dataclass
class AgentMetrics:
    """Потокобезопасный сборщик метрик агентов."""

    _lock: Lock = field(default_factory=Lock, repr=False)
    _node_executions: dict[tuple[str, str], int] = field(default_factory=lambda: defaultdict(int), repr=False)
    _errors: dict[tuple[str, str], int] = field(default_factory=lambda: defaultdict(int), repr=False)
    _escalations: dict[str, int] = field(default_factory=lambda: defaultdict(int), repr=False)
    _hitl_denies: dict[str, int] = field(default_factory=lambda: defaultdict(int), repr=False)
    _extract_refusals: dict[str, int] = field(default_factory=lambda: defaultdict(int), repr=False)
    _extract_skips: dict[str, int] = field(default_factory=lambda: defaultdict(int), repr=False)
    _lint_findings: dict[tuple[str, str], int] = field(default_factory=lambda: defaultdict(int), repr=False)
    _schema_outcomes: dict[tuple[str, str], int] = field(default_factory=lambda: defaultdict(int), repr=False)
    _citation_outcomes: dict[tuple[str, str], int] = field(default_factory=lambda: defaultdict(int), repr=False)
    _highlight_outcomes: dict[str, int] = field(default_factory=lambda: defaultdict(int), repr=False)
    _judge_scores: dict[str, int] = field(default_factory=lambda: defaultdict(int), repr=False)
    _judge_failures: dict[str, int] = field(default_factory=lambda: defaultdict(int), repr=False)
    _rbac_denies: dict[tuple[str, str], int] = field(default_factory=lambda: defaultdict(int), repr=False)
    _context_tokens: dict[str, int] = field(default_factory=lambda: defaultdict(int), repr=False)
    _secret_redactions: dict[tuple[str, str], int] = field(default_factory=lambda: defaultdict(int), repr=False)
    _pii_detections: dict[tuple[str, str], int] = field(default_factory=lambda: defaultdict(int), repr=False)
    _constitution_violations: dict[tuple[str, str], int] = field(default_factory=lambda: defaultdict(int), repr=False)
    _attachment_parses: dict[tuple[str, str], int] = field(default_factory=lambda: defaultdict(int), repr=False)
    _attachment_reads: dict[tuple[str, str, str, str], int] = field(
        default_factory=lambda: defaultdict(int),
        repr=False,
    )
    _vision_images: dict[tuple[str, str], int] = field(default_factory=lambda: defaultdict(int), repr=False)

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
        _palatium_agent_request_duration_seconds.labels(agent_type=agent_type, node_name=node_name).observe(safe_duration)

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

    def record_grounding_mode(self, mode: str) -> None:
        safe = (mode or "optional").strip()[:32] or "optional"
        _palatium_grounding_mode_total.labels(mode=safe).inc()

    def record_grounding_degraded(self, mode: str = "optional") -> None:
        safe = (mode or "optional").strip()[:32] or "optional"
        _palatium_grounding_degraded_total.labels(mode=safe).inc()

    def record_grounding_required_empty(self) -> None:
        _palatium_grounding_required_empty_total.inc()

    def record_grounding_satisfied(self, mode: str = "optional") -> None:
        safe = (mode or "optional").strip()[:32] or "optional"
        _palatium_grounding_satisfied_total.labels(mode=safe).inc()

    def record_grounding_flag_off(self) -> None:
        _palatium_grounding_flag_off_total.inc()

    def record_grounding_rollout(self, *, enabled: bool) -> None:
        _palatium_grounding_rollout_total.labels(enabled="true" if enabled else "false").inc()

    def record_grounding_hallucination(self) -> None:
        _palatium_grounding_hallucination_total.inc()

    def record_grounding_judge_run(self) -> None:
        _palatium_grounding_judge_runs_total.inc()

    def record_grounding_judge_failed(self) -> None:
        _palatium_grounding_judge_failed_total.inc()

    def record_judge_score(self, *, dimension: str, score: float) -> None:
        """One decomposed-judge verdict; the dimension label is the closed axis set."""
        safe = (dimension or "unknown").strip()[:32] or "unknown"
        _palatium_judge_score.labels(dimension=safe).observe(min(max(float(score), 0.0), 1.0))
        with self._lock:
            self._judge_scores[safe] += 1

    def record_judge_failed(self, *, dimension: str) -> None:
        """A judge call produced no score: that axis is unmeasured (never a pass)."""
        safe = (dimension or "unknown").strip()[:32] or "unknown"
        _palatium_judge_failed_total.labels(dimension=safe).inc()
        with self._lock:
            self._judge_failures[safe] += 1

    def judge_score_count(self, dimension: str) -> int:
        with self._lock:
            return self._judge_scores[dimension]

    def judge_failure_count(self, dimension: str) -> int:
        with self._lock:
            return self._judge_failures[dimension]

    def record_grounding_clarification(self, *, query_hash: str, len_bucket: str) -> None:
        safe_hash = (query_hash or "empty").strip()[:16] or "empty"
        safe_bucket = (len_bucket or "empty").strip()[:16] or "empty"
        _palatium_grounding_clarification_total.labels(
            query_hash=safe_hash,
            len_bucket=safe_bucket,
        ).inc()

    def record_transform(self, *, kind: str) -> None:
        """Count requested prior-content transformation kind (none/restructure/…)."""
        safe = (kind or "none").strip()[:32] or "none"
        _palatium_transform_total.labels(kind=safe).inc()

    def record_response_shape(self, *, shape: str, outcome: str) -> None:
        """Count the requested shape (outcome=requested) and whether it was met.

        ``outcome`` is a closed value set at the call sites: ``requested`` (axis was
        carried into the turn), ``satisfied`` / ``mismatch`` (checked on the document).
        """
        safe_shape = (shape or "auto").strip()[:32] or "auto"
        safe_outcome = (outcome or "unknown").strip()[:32] or "unknown"
        _palatium_response_shape_total.labels(shape=safe_shape, outcome=safe_outcome).inc()

    def record_answer_writer(self, *, owner: str, reason: str) -> None:
        """Count turns by resolved writer (P1a single-writer axis)."""
        safe_owner = (owner or "formatter").strip()[:32] or "formatter"
        safe_reason = (reason or "unknown").strip()[:64] or "unknown"
        _palatium_answer_writer_total.labels(owner=safe_owner, reason=safe_reason).inc()

    def record_content_lint_finding(self, *, rule: str, severity: str) -> None:
        """Count a deterministic ContentDocument defect; the answer is not changed."""
        safe_rule = (rule or "unknown").strip()[:64] or "unknown"
        safe_severity = (severity or "warning").strip()[:16] or "warning"
        with self._lock:
            self._lint_findings[(safe_rule, safe_severity)] += 1
        _palatium_content_lint_findings_total.labels(rule=safe_rule, severity=safe_severity).inc()

    def content_lint_finding_count(self, rule: str, severity: str) -> int:
        with self._lock:
            return self._lint_findings[(rule, severity)]

    def record_formatter_schema(self, *, path: FormatterGenerationPath, outcome: FormatterSchemaOutcome) -> None:
        """Count one generation attempt by contract and schema verdict (W0b).

        The schema-validity rate is ``valid / (valid + invalid)``. ``unsupported``
        carries no verdict and ``empty_blocks`` is a content defect, not a schema
        failure — folding either into the ratio would hide the real signal (040).
        Transport failures are counted by ``record_error``, not here.
        """
        _palatium_formatter_schema_total.labels(path=path, outcome=outcome).inc()
        with self._lock:
            self._schema_outcomes[(path, outcome)] += 1

    def formatter_schema_count(self, path: str, outcome: str) -> int:
        with self._lock:
            return self._schema_outcomes[(path, outcome)]

    def record_citation_resolution(self, *, anchor: str, outcome: str) -> None:
        """Count one provider citation by anchor and resolution outcome (W3a).

        Emitted-vs-resolved is read off this counter, so every citation the provider
        returned must be counted exactly once — including the dropped ones, otherwise
        the resolution rate silently improves by dropping hard cases.
        """
        safe_anchor = (anchor or "url_only").strip()[:32] or "url_only"
        safe_outcome = (outcome or "resolved").strip()[:32] or "resolved"
        _palatium_citation_resolution_total.labels(anchor=safe_anchor, outcome=safe_outcome).inc()
        with self._lock:
            self._citation_outcomes[(safe_anchor, safe_outcome)] += 1

    def citation_resolution_count(self, anchor: str, outcome: str) -> int:
        with self._lock:
            return self._citation_outcomes[(anchor, outcome)]

    def record_citation_highlight(self, *, outcome: str) -> None:
        """Count one source-highlight request by locate outcome (W3b-2).

        Every request is counted, including ``quote_not_found`` / ``ambiguous_quote``:
        a highlight rate that only counts successes would measure the easy quotes.
        """
        safe_outcome = (outcome or "no_text").strip()[:32] or "no_text"
        _palatium_citation_highlight_total.labels(outcome=safe_outcome).inc()
        with self._lock:
            self._highlight_outcomes[safe_outcome] += 1

    def citation_highlight_count(self, outcome: str) -> int:
        with self._lock:
            return self._highlight_outcomes[outcome]

    def record_grounding_latency(
        self,
        *,
        mode: str,
        degraded: bool,
        duration_seconds: float,
    ) -> None:
        safe_mode = (mode or "optional").strip()[:32] or "optional"
        _palatium_grounding_latency_seconds.labels(
            mode=safe_mode,
            degraded="true" if degraded else "false",
        ).observe(max(0.0, float(duration_seconds)))

    @staticmethod
    def grounding_latency_buckets() -> tuple[float, ...]:
        return GROUNDING_LATENCY_BUCKETS

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

    def record_llm_cost_missing(self, *, reason: str) -> None:
        """Count completions where tokens > 0 but USD could not be resolved (040)."""
        safe = (reason or "unknown").strip()[:64] or "unknown"
        _palatium_llm_cost_missing_total.labels(reason=safe).inc()

    def record_llm_fallback(self, *, to_provider: str) -> None:
        """Count successful failovers onto a secondary LLM provider (020)."""
        safe = (to_provider or "unknown").strip()[:64] or "unknown"
        _palatium_llm_fallback_total.labels(to_provider=safe).inc()

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

    def record_pii_detected(self, *, kinds: tuple[str, ...], profile: str) -> None:
        """Count detected PII spans per class and boundary (020, 040).

        ``kinds`` come from a :class:`PiiScan` — kinds only, never the matched value,
        so the label set stays closed (six classes) and the metric cannot leak.
        """
        safe_profile = (profile or "unknown").strip()[:32] or "unknown"
        with self._lock:
            for kind in kinds:
                safe_kind = (kind or "unknown").strip()[:32] or "unknown"
                self._pii_detections[(safe_kind, safe_profile)] += 1
                _palatium_pii_detected_total.labels(kind=safe_kind, profile=safe_profile).inc()

    def pii_detection_count(self, kind: str, profile: str) -> int:
        with self._lock:
            return self._pii_detections[(kind, profile)]

    def record_constitution_violation(self, *, principle: str, source: str) -> None:
        """Count a violated constitution article (020, 040).

        ``source`` separates a code-proven violation from a judged one: they need
        different responses — a regex failure is a bug, a judge finding is a review.
        """
        safe_principle = (principle or "unknown").strip()[:64] or "unknown"
        safe_source = (source or "unknown").strip()[:32] or "unknown"
        with self._lock:
            self._constitution_violations[(safe_principle, safe_source)] += 1
        _palatium_constitution_violation_total.labels(principle=safe_principle, source=safe_source).inc()

    def constitution_violation_count(self, principle: str, source: str) -> int:
        with self._lock:
            return self._constitution_violations[(principle, source)]

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

    def record_attachment_read(
        self,
        *,
        kind: str,
        ocr_applied: bool,
        ocr_engine: str,
        ocr_cached: bool,
    ) -> None:
        """Count ``platform.read_attachment`` outcomes (closed label sets, 040)."""
        safe_kind = (kind or "unknown").strip()[:32] or "unknown"
        applied = "true" if ocr_applied else "false"
        safe_engine = (ocr_engine or "none").strip()[:32] or "none"
        cached = "true" if ocr_cached else "false"
        with self._lock:
            self._attachment_reads[(safe_kind, applied, safe_engine, cached)] += 1
        _palatium_attachment_read_total.labels(
            kind=safe_kind,
            ocr_applied=applied,
            ocr_engine=safe_engine,
            ocr_cached=cached,
        ).inc()

    def attachment_read_count(
        self,
        *,
        kind: str,
        ocr_applied: bool,
        ocr_engine: str,
        ocr_cached: bool,
    ) -> int:
        applied = "true" if ocr_applied else "false"
        cached = "true" if ocr_cached else "false"
        with self._lock:
            return self._attachment_reads[(kind, applied, ocr_engine, cached)]

    def record_vision_image(self, *, outcome: str, reason: str) -> None:
        """Count one chat image part by admission outcome (ADR 0007, closed labels)."""
        safe_outcome = (outcome or "unknown").strip()[:16] or "unknown"
        safe_reason = (reason or "none").strip()[:32] or "none"
        with self._lock:
            self._vision_images[(safe_outcome, safe_reason)] += 1
        _palatium_vision_image_total.labels(outcome=safe_outcome, reason=safe_reason).inc()

    def vision_image_count(self, *, outcome: str, reason: str) -> int:
        with self._lock:
            return self._vision_images[(outcome, reason)]

    def record_memory_query_duration(self, duration_seconds: float) -> None:
        _palatium_memory_query_duration_seconds.observe(max(0.0, duration_seconds))

    def record_memory_entry_size(self, *, memory_type: str, size_bytes: int) -> None:
        safe_type = (memory_type or "unknown").strip()[:32] or "unknown"
        _palatium_memory_entry_size_bytes.labels(memory_type=safe_type).observe(max(0, size_bytes))

    def record_memory_extract_queue(self, *, depth: int, lag_seconds: float, dead: int = 0) -> None:
        """Publish durable extract queue depth / lag / DLQ size (Wave M3)."""
        _palatium_memory_extract_queue_depth.set(max(0, int(depth)))
        _palatium_memory_extract_queue_lag_seconds.set(max(0.0, float(lag_seconds)))
        _palatium_memory_extract_dead_letter_total.set(max(0, int(dead)))

    def record_memory_extract_enqueue_refused(self, *, reason: str) -> None:
        """Count a refused enqueue by ceiling: ``queue_full`` (global) or ``tenant_full`` (M3 E7)."""
        safe_reason = (reason or "unknown").strip()[:32] or "unknown"
        with self._lock:
            self._extract_refusals[safe_reason] += 1
        _palatium_memory_extract_enqueue_refused_total.labels(reason=safe_reason).inc()

    def memory_extract_enqueue_refused_count(self, reason: str) -> int:
        with self._lock:
            return self._extract_refusals[reason]

    def record_memory_extract_skipped(self, *, reason: str) -> None:
        """Count turns whose extract was skipped by policy, not by capacity (060)."""
        safe_reason = (reason or "unknown").strip()[:64] or "unknown"
        with self._lock:
            self._extract_skips[safe_reason] += 1
        _palatium_memory_extract_skipped_total.labels(reason=safe_reason).inc()

    def memory_extract_skipped_count(self, reason: str) -> int:
        with self._lock:
            return self._extract_skips[reason]

    def record_memory_recall_at_k(self, *, k: int, value: float) -> None:
        """Publish offline-eval Recall@k (0..1). Runtime traffic must not call this."""
        safe_k = str(max(1, min(int(k), 50)))
        clamped = max(0.0, min(1.0, float(value)))
        _palatium_memory_recall_at_k.labels(k=safe_k).set(clamped)

    def record_memory_promote_error(self, *, error_type: str = "runtime") -> None:
        """Count a promote-batch failure (job / GraphWritePort)."""
        safe = (error_type or "runtime").strip()[:64] or "runtime"
        _palatium_memory_promote_errors_total.labels(error_type=safe).inc()

    def record_memory_promote_blocked_pii(self, *, count: int = 1) -> None:
        """Count PII supersedes withheld for a human decision (M5 audit F3)."""
        _palatium_memory_promote_blocked_pii_total.inc(max(1, int(count)))

    def record_memory_recall_source(self, *, source: str) -> None:
        """Count hot-path Select by source (scratchpad/medium/graph/skipped_*)."""
        safe = (source or "unknown").strip()[:64] or "unknown"
        _palatium_memory_recall_source_total.labels(source=safe).inc()

    def record_attachment_sticky(self, *, action: str) -> None:
        """Count sticky attachment policy actions (SB0/SB1)."""
        safe = (action or "unknown").strip()[:64] or "unknown"
        _palatium_attachment_sticky_total.labels(action=safe).inc()

    def record_turn_duration(
        self,
        *,
        task_kind: str,
        strategy: str,
        duration_seconds: float,
    ) -> None:
        kind = (task_kind or "unknown").strip()[:64] or "unknown"
        strat = (strategy or "unknown").strip()[:64] or "unknown"
        _palatium_turn_duration_seconds.labels(task_kind=kind, strategy=strat).observe(max(0.0, float(duration_seconds)))

    def record_llm_ttft(self, duration_seconds: float) -> None:
        _palatium_llm_ttft_seconds.observe(max(0.0, float(duration_seconds)))

    def record_sse_ttft(self, duration_seconds: float) -> None:
        """First answer_delta after process_stream bind (user-visible TTFT)."""
        _palatium_sse_ttft_seconds.observe(max(0.0, float(duration_seconds)))

    def record_sse_first_block(self, duration_seconds: float) -> None:
        """First typed ``block_delta``: the structured preview's real start."""
        _palatium_sse_first_block_seconds.observe(max(0.0, float(duration_seconds)))

    def record_sse_layout_shift(self, *, contract: str) -> None:
        """Count a frame that overwrites content already shown to the user.

        A ``replace`` frame is correct only for the deprecated
        ``legacy_markdown`` migration contract (dual-emit). Under the
        structured contract this must stay at zero; a non-zero rate is an alert,
        not a metric to watch (040).
        """
        safe = (contract or "unknown").strip()[:32] or "unknown"
        _palatium_sse_layout_shift_total.labels(contract=safe).inc()

    def record_utf8_decode_failure(self, *, kind: str) -> None:
        """Bytes were replaced by U+FFFD: extracted text is lossy for this upload.

        Silent ``errors="replace"`` masks a real defect (mojibake, truncated OCR,
        wrong encoding guess); the counter makes it visible in dashboards (040).
        """
        safe = (kind or "unknown").strip()[:32] or "unknown"
        _palatium_utf8_decode_failures_total.labels(kind=safe).inc()

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

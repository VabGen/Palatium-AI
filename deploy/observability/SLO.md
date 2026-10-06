# SLI / SLO map — palatium-ai

Source of targets: `docs/max-pro-level-tz.md` §15. Source of metric names:
`src/palatium_ai/core/observability/metrics.py` (rule 040 — closed registry).

**Honesty rule for this table:** an SLO is listed as *monitored* only if a
Prometheus alert in `prometheus/alerts/` actually fires on it. Everything else is
explicitly marked as measured elsewhere, so nobody assumes coverage that isn't there.

## Monitored now

| # | SLO (§15) | Target | SLI / PromQL | Alert | Severity |
|---|---|---|---|---|---|
| 1 | Agent success rate | > 95% | `palatium:agent_success_ratio:5m` = 1 − `rate(palatium_agent_errors_total)` / `clamp_min(rate(palatium_agent_request_duration_seconds_count), …)` | `PalatiumAgentSuccessRateBelowSlo` (<0.95 for 15m), `PalatiumAgentSuccessRateCritical` (<0.90 for 10m) | warning / critical |
| 2 | Memory query latency p95 | < 200 ms | `palatium:memory_query_p95_seconds:5m` = `histogram_quantile(0.95, rate(palatium_memory_query_duration_seconds_bucket[5m]))` | `PalatiumMemoryQueryLatencyHigh` (>0.2s for 10m) | warning |
| 3 | Circuit breaker false-open rate | ~ 0 | `max_over_time(palatium_circuit_breaker_state[5m]) == 2` (2 = open; 1 = half-open is normal recovery) | `PalatiumCircuitBreakerOpen` (5m) | warning |
| 4 | Audit chain integrity | 100% daily | `increase(palatium_audit_write_failures_total[10m]) > 0` | `PalatiumAuditChainWriteFailure` (1m) | critical |
| 5 | Availability (implicit) | scrape succeeds | `up{job="palatium-api"}` | `PalatiumApiDown` (2m) | critical |

`clamp_min(..., 0.001)` is deliberate: with zero traffic the numerator is also
zero, so the ratio is 1.0 (no data ≠ 100% failure). The alternative —
treating "no series" as breach — pages on a quiet system.

## Control alerts (not SLO burn, but safety-critical)

| Control | Signal | Alert | Severity |
|---|---|---|---|
| HITL card single-use (020) | `increase(palatium_hitl_card_replay_rejected_total[10m]) > 0` | `PalatiumHitlCardReplayRejected` | critical |
| RBAC allow-list (020) | `sum(rate(palatium_rbac_denied_total[5m])) > 0.2` | `PalatiumRbacDenialSpike` | warning |
| HITL deny paths | `sum(rate(palatium_hitl_deny_total[15m])) > 0.2` | `PalatiumHitlDenySpike` | warning |
| Turn latency budget | `increase(palatium_turn_hop_budget_exceeded_total[15m]) > 5` | `PalatiumTurnHopBudgetExceeded` | warning |
| Cost budget | `palatium:llm_cost_usd_per_hour:1h > 1` | `PalatiumLlmCostBurnHigh` | warning |
| Context discipline (065) | `sum(rate(palatium_context_tokens_used[15m])) > 20000` | `PalatiumContextTokensHigh` | warning |
| Memory entry hygiene (060) | `histogram_quantile(0.95, …palatium_memory_entry_size_bytes_bucket…) > 16384` | `PalatiumMemoryEntryOversized` | info |
| Extract DLQ (060 / M3) | `palatium_memory_extract_dead_letter_total > 0` | `PalatiumMemoryExtractDeadLetter` | warning |
| Promote batch errors (060 / M7) | `sum(rate(palatium_memory_promote_errors_total[15m])) > 0` | `PalatiumMemoryPromoteErrors` | warning |

## NOT monitored in Prometheus — and why

These four SLOs are real commitments but are **not** Prometheus signals. None of
them has an alert, and adding a fake one would be worse than the gap.

| SLO | Where it is actually enforced | Note |
|---|---|---|
| Memory Recall@k > 85% | Offline eval — `tests/eval/test_memory_failure_modes_m7.py` (+ spine/live) | Ground truth required; metric `palatium_memory_recall_at_k{k}` is **offline-eval only** (Pushgateway / test publish). No Prom alert — alert would page on missing push, not on real IR degradation. |
| Coverage `domain/policies` ≥ 90% | CI gate — `scripts/ci_quality.py` | Build-time, not runtime. |
| Benchmark success rate > 85% | Offline eval — `scripts/run_agent_evals.py` (`artifacts/agent_evals.json`, nightly workflow) | Deterministic in PR, LLM-judge nightly. |
| Audit chain verification 100% daily | Cron — `.github/workflows/audit-chain-daily.yml` | Prometheus only sees write failures (#4); the daily re-hash of the whole chain lives in that job. A `pushgateway` metric would be the way to surface it here. |

## Decision (M7, 2026-10-06)

`palatium_memory_recall_at_k{k}` is an **offline eval Gauge** (option 1):
published from eval jobs / Pushgateway via `AgentMetrics.record_memory_recall_at_k`.
Runtime hot-path must **not** write this metric as a hit-rate proxy (would
mislabel the SLO). No Prometheus alert on the Gauge — CI/nightly eval is the gate.

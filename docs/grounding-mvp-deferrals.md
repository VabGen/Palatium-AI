# Grounding MVP — deferrals

**Date:** 2026-10-14  
**Scope:** Adaptive Grounding Core MVP (`ADAPTIVE_GROUNDING_ENABLED` + sticky `ADAPTIVE_GROUNDING_ROLLOUT_PCT`)  
**Code phase:** closed. Further progress needs staging data (baseline → shadow → PCT).  
**Next phase:** follow **Pre-flip sequence** below — do **not** jump to `PCT=10` without shadow.

Related: plan `.cursor/plans/grounding_adaptive_rag_*.plan.md`; merge semantics —
`merge_parallel_worker_results` in `application/orchestration/agent_bridge.py`.

---

## Pre-flip sequence (mandatory)

`PCT=10` только после 24h shadow. Без shadow шаг 3 — первое измерение adaptive-пути сразу на пользователях.

1. OFF baseline ≥ 7d (min N per validity gates)
2. Shadow 24h (`ENABLED=true`, `PCT=0`, `SHADOW=true`)
3. `PCT=10` → 7d → compare against baseline
4. `PCT=50` → 7d → compare
5. `PCT=100`

---

## Feature flag semantics

`ADAPTIVE_GROUNDING_ENABLED` — master switch  
`ADAPTIVE_GROUNDING_ROLLOUT_PCT` — distribution (0..100), sticky per-user via `hash8(user_id)`

**Two-key:** feature is ON iff `ENABLED=true` **and** `PCT>0`.

| Config | Effect |
|---|---|
| `ENABLED=true`, `PCT=0` | OFF + startup warning `adaptive_grounding.enabled_but_zero_rollout` |
| `ENABLED=true`, `PCT=100` | ON for all (used in ON-tests / full cutover) |
| `ENABLED=true`, `PCT=10` | ON for ~10% stable cohort |
| `ENABLED=false`, `PCT=*` | OFF |

**Rollback:** set `PCT=0` (keep `ENABLED=true` so re-rollout is one variable).  
Do **not** default `PCT` to 100 — that would make a lone `ENABLED=true` flip a global cutover footgun.

Startup warning: `warn_if_enabled_but_zero_rollout` from `setup_observability`, called only inside FastAPI **lifespan** (`presentation/app.py` → `application.bootstrap.startup`) — not at import time. Smoke on staging: `ENABLED=true`, `PCT=0` → event in logs **before** the first request.

### Shadow mode (required before PCT>0; code TBD)

`ADAPTIVE_GROUNDING_SHADOW=true` at `ENABLED=true`, `PCT=0`:

- adaptive path runs; metrics and latency are written
- user-facing response stays the legacy soft-empty stub
- compare quality/latency **before** flipping PCT

Gate: shadow ≥ 24h, then `PCT=10` (see Pre-flip sequence).  
Pattern: dark launch — observe without user risk. Implementation is still deferred; sequence above is mandatory once the flag exists.

---

## Pre-flip hardening (done before staging rollout)

- [x] Redaction at observability boundaries (`core/observability/redaction.py` + structlog processor)
- [x] Custom latency buckets (0.1s … 60s) on `palatium_grounding_latency_seconds`
- [x] Sticky per-user rollout (`hash8(user_id) % 100`, `ADAPTIVE_GROUNDING_ROLLOUT_PCT`)
- [x] Hallucination guardrail (sampled fire-and-forget LLM-judge)
- [x] Clarification counter with `query_hash` + `len_bucket` (never raw query)
- [x] CI lint on raw query in logs/metrics/OTel (`scripts/lint_observability.py`)
- [x] Canary alert notes: Loki token leak + Prometheus hallucination/degraded-ratio

## Rollback triggers (flip ON only with these watched)

| Trigger | Action |
|---|---|
| p95(ON) / p95(OFF) > 2.0 | pause rollout |
| required_empty / required > 0.30 | pause, review clarification template |
| hallucination_total / judge_runs_total > 0.05 | rollback |
| 5xx error rate > 2× baseline | rollback |
| flag_off_total drops to 0 at rollout_pct>0 while OFF cohort expected | config not propagated to pods |

## Baseline validity gates

- Optional bucket needs ≥ 200 turns for percentage metrics.
- p95 needs ≥ 500 turns. Shorter window → extend.

## Dashboard + alerts (SoT in git)

Grafana: `deploy/observability/grafana/dashboards/palatium-adaptive-grounding.json`  
Prometheus: group `palatium-adaptive-grounding` in `deploy/observability/prometheus/alerts/palatium-platform.yml`  
Loki canaries: `deploy/observability/loki/canary-token-leak.md`

Labels: counters use `mode=` (not `grounding=`). Panel **2.2 default_used** is a placeholder until the counter exists.

### First hour after PCT flip

1. Panel 1.1: `enabled="true"` > 0, доля ≈ PCT.
2. Panel 1.2: flag_off ratio not stuck at ~1 when PCT≈100; at PCT=10 OFF cohort is expected.
3. Panel 3.4: clarification top-N ≤ ~10 distinct `query_hash` (not cardinality explosion).
4. Panel 4.1 / 4.3: latency not all in `+Inf`.
5. Panel 5.1: `judge_runs` ≥ 1/h when degraded ≥ ~100/h at sample=1%.
6. Logs: no `enabled_but_zero_rollout` after intentional `PCT>0` (expect it only at PCT=0).

All six green → leave overnight. Panel 3.1 red in first 30m → not “wait for N”; pause and check corpus vs classifier (`optional` vs `required`).

**Degraded ratio within optional** (panel 3.1; green <0.5, yellow 0.5–0.7, red >0.7):

```promql
sum(rate(palatium_grounding_degraded_total{mode="optional"}[30m]))
/
(
  sum(rate(palatium_grounding_degraded_total{mode="optional"}[30m]))
  +
  sum(rate(palatium_grounding_satisfied_total{mode="optional"}[30m]))
)
```

**Top-10 clarification by query_hash** (panel 3.4):

```promql
topk(10, sum by (query_hash, len_bucket) (rate(palatium_grounding_clarification_total[1h])))
```

---

## Redis-кэш grounding-классификации

| | |
|---|---|
| **Причина** | Cost/latency-налог на повторный Intent LLM; не влияет на корректность. |
| **Критерий возврата** | Повторяемость нормализованных запросов >20% в недельном срезе staging/prod. |
| **Owner** | TBD |

## Critic skip / ungrounded judge

| | |
|---|---|
| **Причина** | Revision уже блокируется `requires_clarification` / terminal MCP codes; Critic всё равно вызывается. |
| **Влияние** | +latency на clarification/degraded путях, не incorrectness. |
| **Критерий возврата** | p95 latency на clarification-пути >3s, или отдельный ungrounded-judge нужен по quality eval. |
| **Owner** | TBD |

## Rich Formatter I/O (`content` / `grounded` / `sources[]` / …)

| | |
|---|---|
| **Причина** | MVP хватает summary + RU disclaimer prefix; Formatter остаётся text-in. |
| **Риск** | Фича «покажи источники» потребует расширения контракта — не изобретать заново. |
| **Критерий возврата** | Product-запрос на provenance UI / cite sources, или Critic нужен structured evidence. |
| **Owner** | TBD |

## Метрики: `default_used`, `reason` labels

| | |
|---|---|
| **Причина** | Не блокер MVP; есть `mode` / `degraded` / `required_empty` / `satisfied` / `flag_off` + latency histogram. |
| **Критерий возврата** | Нужна диагностика silent default→optional или split empty vs MCP error на дежурстве. |
| **Owner** | TBD |

## Parallel tools: `tool_relation` (complementary vs alternative)

| | |
|---|---|
| **Причина** | Сейчас нет сигнала в plan/state; strict OR-merge — единственный корректный default. |
| **Критерий возврата** | Появление альтернативных tool-планов («найди хоть что-то»), где any-satisfied был бы правильнее. |
| **Owner** | TBD |

---

## Staging A/B (следующий шаг после merge)

### Неделя 1 — baseline + smoke

Следовать **Pre-flip sequence** (mandatory): baseline → shadow 24h → только потом `PCT=10`.

1. OFF baseline ≥ 7d: `ENABLED=false` **или** (`ENABLED=true` + `PCT=0` без shadow). При `ENABLED=true`+`PCT=0` ожидайте startup warning до первого запроса — rollback path, не баг.
2. Shadow 24h (`ENABLED=true`, `PCT=0`, `SHADOW=true`) — метрики adaptive-пути без user-facing change.
3. `ENABLED=true` + `ROLLOUT_PCT=10` (sticky) → 7d; OFF cohort continues via hash. Проверить counters `mode/degraded/required_empty/satisfied/flag_off/rollout` + latency histogram (не нули).
4. Pause/rollback traffic: `ROLLOUT_PCT=0` (leave `ENABLED=true`).

### Неделя 2 — сравнение

- `ROLLOUT_PCT=50`.
- Смотреть:
  - **Δ % ответов без «ничего не найдено»** — главная метрика.
  - Δ p95 latency — окупается ли optional→LLM reason.
  - Распределение `grounding ∈ {required, optional, none}`.
  - % `degraded` внутри `optional` — если **>70%**, корпус пустой: фича маскирует данные, не чинит UX → тормозить.
  - % `required_empty` — если **>20%**, clarification-шаблон = горячий путь.

### Gate для rolling на prod

| Gate | Порог |
|---|---|
| Δ заглушек | −80% или лучше |
| Δ p95 latency | +30% или меньше |
| `default_used` (когда заведёте) | <5% |

Если p95 вырос сильнее — стоп, смотреть researcher vs formatter.  
Если `% degraded` внутри optional >70% — стоп, наполнять корпус.

# 0011. Observability, cost & contracts (W7–W8)

- **Статус:** accepted
- **Дата:** 2026-11-10
- **Правило-владелец:** 030 / 040 / 075 / ADR-0009 / ADR-0010

## Контекст

W1–W6 закрыли verify/handoffs/behavioral/inventory (ADR-0009, ADR-0010). Отложенные
направления — cost-first observability, freshness контекста субагентов, единые
retry/caps/logging/OTel/I-O-контракты и pin Constitution — нужны, чтобы
мультиагентный рост токенов и дрейф verify не оставались слепыми.

## Решение

### Scope

Cost metrics, context freshness, agent I/O schema contracts, unified retry,
concurrency caps, structured logging / OTel `agent.run`, prompt versioning,
eval coverage map. **Не** меняет оркестрацию и не добавляет агентов.

### Policy decisions

1. **Single LLM chokepoint (W7.2)** — агенты вызывают LLM только через
   `Harness.call_llm` / `call_llm_stream`. AST-тест
   `test_w7_no_llm_calls_outside_wrapper`. Метрики
   `palatium_llm_tokens_total{agent,model,direction}` (`input`|`output`) и
   `palatium_llm_cost_usd_total{agent,model}` dual-write рядом с legacy series.
   Прайс — `core/config/llm_pricing.py` (`PRICING_VERSION`); смена →
   `[pricing-update]`.
2. **Fresh context by default (W7.1)** — sharing только через explicit handoff
   payload (ADR-0009 § Handoff payload). **Isolation proof** =
   `assert_fresh_handoff_context` (keys ⊆ allow-list ∧ ∩ pollution = ∅).
   `palatium_subagent_context_ratio` / `max_context_ratio` — только
   **regression guard** на size drift (ratio > 1 нормален для researcher
   scaffolding); не доказательство изоляции.
3. **Schema mismatch = fail-closed verify (W8.4)** — harness проверяет
   `ROLE_OUTPUT_TYPES` *до* `agent.verify` / LLM-judge; mismatch →
   `status=failure`, `verify_failed_{role}`, reason `schema_mismatch:*`.
4. **Retry не применяется к verify failure (W8.3)** — единый `RetryPolicy` +
   `is_transient_llm_error`; permanent 4xx/validation без retry; verify path
   вне retry-цикла (`RetryOutcome.verify_skip`).
5. **Caps — явная ошибка, не silent drop (W8.5)** —
   `max_parallel_subagents` / `max_total_subagents_per_run` →
   `SubagentCapExceededError` + `palatium_subagent_cap_hits_total{cap}`.

**Cost channels:** CI `behavioral.json` pins `max_cost_usd: null`
(`cost_channel: cassette_unmeasured`) — cassette-replay не измеряет USD.
Production cost regression — отдельный сигнал
`palatium_llm_cost_usd_total{agent,model}`, не baseline v3.

**Pricing markers:** `[pricing-update]` обязателен при любом изменении
`get_tier_model_specs` / rates **после** baseline `PRICING_VERSION=2026-11-10.1`
(initial surface этого PR маркером не помечается).

### Enum-контракты

`LLMTokenDirection`, `RetryOutcome`, `SchemaMismatchReason`, `SubagentCapKind`
в `core/types/w78_observability.py` (closed labels, как W5.5).

### Baseline management

`evals/baselines/behavioral.json` **v3**: `actual_* == max_*` для hops и
`max_context_ratio` (size regression). Cost: `null` +
`cost_channel: cassette_unmeasured` (не «измерено как ноль»). Любой подъём
измеримых `max_*` → `[baseline-refresh]` (ADR-0010 §5).

### Review triggers

- смена прайс-таблицы моделей **после** `PRICING_VERSION=2026-11-10.1` →
  `[pricing-update]`;
- Constitution / verify-промпты → `[constitution-update]` + hash в ADR-0010;
- новый агент → coverage map (`test_w8_agent_eval_coverage`);
- не позднее **2027-02-10** (≤3 месяца от 2026-11-10) — пересмотр cost-политики
  после сбора реальных данных (prod metric, не cassette null).

## Рассмотренные альтернативы

- **Второй logging/OTel стек** — отвергнуто: расширяем structlog processors и
  существующий `@traceable` (`agent.run`).
- **Свободные string-labels на cost/caps** — отвергнуто: только enum (040).
- **Retry verify failure «на всякий случай»** — отвергнуто: маскирует контрактный
  провал.

## Последствия

- Cost и freshness — first-class в CI behavioral.
- Constitution drift ловится hash-пином без правки содержимого.
- Следующий аудит — от ADR-0010 + этого ADR, не с чистого листа.

## Ссылки

- [ADR-0009](0009-langgraph-supervisor-workers.md)
- [ADR-0010](0010-agents-audit-w1-w6-closure.md)
- `application/agents/evals/behavioral.py`
- `application/agents/evals/baselines/behavioral.json`

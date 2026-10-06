# Аудит скорости ответа Palatium-AI

**Дата аудита:** 2026-10-01  
**Обновлено после P0–P2:** 2026-10-01  
**Метод:** статическая карта кода + offline L1 bench + live probe API (`scripts/benchmark_latency.py`).  
**Точка входа:** `POST /api/intents/process` (+ SSE `…/process/stream`) → `IntentService` → LangGraph.

> Числа без пометки «замер» — оценочные порядки по архитектуре. Замеры — §5.

---

## 0. Executive Summary (после P0–P2)

| Метрика | Сейчас | Цель |
|---|---|---|
| P50 simple («привет») wall | **замер:** ~0.66 с warm / ~5.3 с cold (n=2+2) | &lt;1 с |
| P50 simple L1 hit (offline) | **замер** P50/P95 **0.1 мс** (n=200, in-memory) | &lt;50 мс |
| P95 complex (knowledge) wall | **замер:** ~1.0 с warm / ~9.0 с cold | &lt;10 с |
| TTFT (воспринимаемый) | SSE в **коде**; running image → **404** (нужен redeploy) | &lt;500 мс |
| LLM-вызовов на simple | **1** (Intent; Formatter = `AckReplyPolicy`) | **1** |
| LLM-вызовов на simple (с prior) | **1** (Intent-first → Contextualizer skip на known social) | **1** |
| App L1 | код + метрики `palatium_cache_*{cache_layer=l1}` | hit rate &gt;40% (prod — Prometheus) |
| Critic tier | **mid** (+ high `worker_confidence` passthrough) | mid / skip |
| LiteLLM routing | `latency-based-routing` | latency-based |
| Gateway engine (SGLang/vLLM/speculative) | **вне репо** — чеклист ops, не внедрено | GPU util &gt;70% |

**Вердикт:** архитектурные рычаги P0–P2 **в коде закрыты**. Warm simple **~0.66 с** — у цели &lt;1 с; cold и L1 live hit — ещё gaps. Running API **без** `/process/stream` (404) — redeploy. Железо gateway (P2.13–14) — **ops-backlog**.

---

## 1. Карта одного запроса (актуальная)

### 1.1 Call chain

```
presentation/api/routers/intents.py
  process | process/stream
  → IntentService.process / process_stream
       L1 get_ack (ack_only exact) ─hit→ finalize cache path
       pre: session / kill_switch / budget / dialog.append
       → IntentGraphRunner.run_graph
            asyncio.gather(dialog, scratchpad, session)
            TurnRecallContext (durable recall deferred)
            graph.ainvoke  # Intent → continuation → …
       → finalize (+ HITL, persist, L1 put_if_cacheable)
```

### 1.2 Топология (`graph.py`)

```
START
 → intent_classifier
 → context_enricher_continuation   # task_kind known → skip LLM на social
 → supervisor                      # 0 LLM
 → context_enricher_weaving        # ExecutionPlanner, 0 LLM
 → route_after_context:
      low-risk (ack/format/clarify) → formatter
      parallel multi-cap → parallel_workers (Researcher∥Analyst)
      else → researcher | coder | analyst
 → critic (workers only; skip на low-risk)
 → [quality_revision → worker|parallel]*
 → formatter → END
```

### 1.3 Сценарии LLM (факт кода после P0–P2)

| Сценарий | LLM hops | Примечание |
|---|---|---|
| A) Simple «привет», 1-й ход | **1** | Intent; Formatter template; Critic skipped; recall skipped |
| B) Simple с prior (social) | **1** | Contextualizer skip при known kind |
| C) Knowledge `retrieve_then_reason` | **3–4** | Intent + Researcher (+ tool) + Critic? + Formatter; Critic mid / passthrough при high worker conf |
| D) Multi-cap research+analytics | как C, но Researcher∥Analyst | `parallel_workers` |
| L1 exact ack hit | **0** LLM | до графа |

### 1.4 TTFT / Total / Startup

| Метрика | Статус |
|---|---|
| **TTFT / perceived** | SSE `/intents/process/stream` + UI `processIntentStream`; hop progress до final `result` |
| **Total** | `palatium_turn_duration_seconds`, `agent.turn.hops`, HTTP via TracingMiddleware → `palatium_agent_request_duration_seconds{agent_type=http,node_name=METHOD}` |
| **Startup** | агенты/граф в lifespan — once |

---

## 2. Inference-движок

| Параметр | Факт в репо |
|---|---|
| Движок | **Не в compose продукта.** LiteLLM → `TIER_*_API_BASE` (corporate gateway). |
| Continuous batching / RadixAttention / speculative | **ops gateway** — ADR `0001`, runbook §5.2 (**не внедрено в этом репо**) |
| LiteLLM routing | **`latency-based-routing`** (`deploy/litellm/config.yaml`) |
| LiteLLM semantic cache | `cache: true`, Redis, similarity 0.95 |
| Prompt caching | Harness `cache_control=ephemeral` + adapter content blocks |
| Fallback tiers | да |

---

## 3. Узкие места — статус

| # | Было | Статус |
|---|---|---|
| 1–2 | Нет 1-LLM / Contextualizer до Intent | **DONE** P0.1 |
| 3 | Нет app L1 | **DONE** P0.2 |
| 4 | Нет prompt cache | **DONE** P0.3 |
| 5 | Нет SSE | **DONE** P1.6 |
| 6 | Critic frontier always | **DONE** P1.7 (`mid` + passthrough) |
| 7–8 | Recall always + seq pre-graph | **DONE** P1.5 / P1.8–9 |
| 9 | `retrieve_then_reason` без retrieval | **DONE** P1.11 → `search_knowledge` |
| 10 | Hop budget без degrade | **DONE** P1.10 |
| 11 | Formatter repairs без budget | **DONE** P1.10 soft-skip |
| 12 | Нет Researcher∥Analyst | **DONE** P2.15 |
| 13 | `simple-shuffle` | **DONE** P2.12 |
| 14 | OCR timeout 120с | **DONE** P2.16 (30с) |
| 15 | Inference engine unknown | **OPEN (ops)** P2.13–14 |
| 16–17 | Нет bench / TTFT metrics | **DONE** P0.4 (+ live §5) |

### Чек-лист Фазы 2 (после фикса)

| # | Тема | Вердикт |
|---|---|---|
| 2.1 Sequential LLM | Workers sequential except `parallel_workers`; Supervisor/Weaver 0 LLM | |
| 2.2 Complexity router | task_kind + ack_only + parallel policy; **1 LLM** social | |
| 2.3 Retrieval | `retrieve_then_reason` → `platform.search_knowledge` | |
| 2.4 Memory bypass | `MemoryRecallPolicy` skip social/capability/format/clarify | |
| 2.5 Cache | L1 app + L2 LiteLLM + prompt `cache_control` | |
| 2.6 LLM count | Simple **1**; complex **3–5** | |
| 2.7 Formatter/Critic | ack_fast_path; Critic mid + passthrough / hop soft-degrade | |
| 2.8 Deadline | soft degrade (не hard abort turn) | |
| 2.9 LiteLLM | latency-based-routing; cache on; prompt cache via messages | |
| 2.10 Streaming | API SSE + UI | |
| 2.11 Engine | External — **open ops** | |
| 2.12 Vision | OCR default 30с; chat requires ready ids | |
| 2.13 N+1 | namespaces `gather`; attachment fence loop всё ещё seq (low priority) | |
| 2.14 Serialization | `model_dump_json` orch overhead — residual | |
| 2.15 Startup | OK | |
| 2.16 AI Gateway | route/cache/skip policies in-app; engine ops external | |

---

## 4. План оптимизации — все пункты DONE (код/docs)

См. историю в git / предыдущие ревизии: P0.1–4, P1.5–11, P2.12–16 закрыты 2026-10-01.
P2.13–14 = **документация + чеклист**; runtime на corporate gateway — §9.

---

## 5. Метрики до/после (замеры 2026-10-01)

### 5.1 Offline L1

```text
poetry run python scripts/benchmark_latency.py
# L1 cache get (offline): n=200 P50=0.1ms P95=0.1ms mean=0.1ms
```

### 5.2 Live API (`http://127.0.0.1:8000`, 2026-10-01 вечер)

Прогон A (ранний, cold gateway):

```text
# simple turn 1: 6935ms / turn 2: 3681ms → P50≈5308ms; complex: 9048ms
```

Прогон B (повтор после прогрева; `--stream --complex`):

```text
poetry run python scripts/benchmark_latency.py --base-url http://127.0.0.1:8000 --stream --complex
# simple turn 1: 679ms
# simple turn 2: 647ms (warm >> L1 — check RESPONSE_CACHE_ENABLED / Redis / image)
# simple /intents/process: n=2 P50=663.0ms P95=677.1ms mean=663.0ms
# WARNING: SSE probe HTTP 404 — running API may lack /process/stream
# complex turn: 1010ms
```

| Метрика | Замер / код | Цель | Комментарий |
|---|---|---|---|
| P50 simple total (warm API) | **663 мс** (n=2, прогон B) | &lt;1 с | ✅ у цели после прогрева gateway |
| P50 simple total (cold) | **5308 мс** (прогон A) | &lt;1 с | cold gateway / cold path |
| P95 complex | **1010 мс** (B) / **9048 мс** (A) | &lt;10 с | ✅ в обоих прогонах |
| LLM calls / simple | **1** (код) | 1 | ✅ |
| L1 get offline | **0.1 мс** | &lt;50 мс | ✅ |
| L1 live warm | **не подтверждён** (warm 0.6–3.7 с ≠ &lt;100 мс) | &lt;50 мс | Redis/env/image lag? |
| SSE TTFT | **404** на running image | &lt;500 мс | код в workspace есть; **передеплоить api** |
| L1 hit rate prod | Prometheus | &gt;40% | scrape staging/prod |
| GPU util | вне репо | &gt;70% | §9 |

**Есть в коде:**  
`palatium_agent_request_duration_seconds`, `palatium_turn_duration_seconds`,  
`palatium_llm_ttft_seconds`, `palatium_cache_hit/miss_total`, hop logs,  
`scripts/benchmark_latency.py` (`--stream` TTFT), TracingMiddleware HTTP timings.

**Residual:** running compose/image отстаёт от workspace (SSE 404); L1 live hit не виден; нет route-template HTTP histogram.

---

## 6. Топ-5 — статус внедрения

| # | Изменение | Статус | Ожидание vs факт |
|---|---|---|---|
| 1 | 1 LLM social | **в коде** | warm wall **~0.66 с** ✅; cold зависит от gateway |
| 2 | L1 response cache | **в коде** | offline ✅; live hit **не** подтверждён |
| 3 | Prompt caching | **в коде** | эффект на gateway зависит от поддержки upstream |
| 4 | Memory bypass + parallel ns | **в коде** | — |
| 5 | SSE | **в коде + UI** | redeploy api: live сейчас **404** |

---

## 7. LLM на узел (факт кода)

| Узел | LLM? | Условие skip | model_tier |
|---|---|---|---|
| intent | **всегда** | — | small |
| continuation | иногда | known self-contained kind / нет prior | small |
| supervisor / weaving | нет | — | — |
| researcher / coder / analyst | да | route | config |
| parallel_workers | 2× parallel | multi-cap plan | mid+ |
| critic | иногда | CriticPolicy / HopBudgetPolicy | **mid** |
| formatter | не всегда | `ack_fast_path`, clarify stub, hop soft-skip repairs | small |

---

## 8. Гипотеза (пересмотр)

| Утверждение | Код сейчас |
|---|---|
| «4–6 LLM на привет» | **Опровергнуто:** simple = **1** LLM |
| «нет роутинга» | **Опровергнуто:** ack_only, worker skip, parallel, Critic passthrough |
| «нет кэша» | **Опровергнуто в коде:** L1 + prompt cache + LiteLLM Redis |
| «главное — архитектура» | **Частично:** архитектура закрыта; **live simple wall** всё ещё упирается в gateway/inference (+ проверить L1 enablement) |

---

## 9. Открытый backlog (вне плана P0–P2 кода)

### 9.1 Corporate gateway (P2.13–14) — **OPEN ops**

Источник: ADR [`docs/adr/0001-inference-gateway-latency.md`](../adr/0001-inference-gateway-latency.md), runbook §5.2.

| # | Действие | Владелец | Статус |
|---|---|---|---|
| 1 | SGLang RadixAttention **или** vLLM continuous batching | gateway ops | OPEN |
| 2 | Speculative decoding (draft=nano, target=mid/frontier) | gateway ops | OPEN |
| 3 | ≥2 реплики на alias для `latency-based-routing` | LiteLLM ops | OPEN |
| 4 | Экспорт GPU util / gateway TTFT | observability | OPEN |

### 9.2 Product residual

| # | Тема | Статус |
|---|---|---|
| 1 | Live simple &lt;1 с (warm) | **замер ✅** ~0.66 с; cold ~5 с — gateway |
| 2 | SSE TTFT в `benchmark_latency.py --stream` | **код ✅**; live 404 → **redeploy api** |
| 3 | L1 live hit | **не подтверждён**; `RESPONSE_CACHE_*` добавлен во все env examples; сверить Redis + image |
| 4 | Attachment fence loop sequential | low priority OPEN |
| 5 | Route-template HTTP histogram | OPEN (есть METHOD-only) |

**Повторить замер:**

```powershell
poetry run python scripts/benchmark_latency.py
poetry run python scripts/benchmark_latency.py --base-url http://127.0.0.1:8000 --stream --complex
```

# План: Memory MAX PRO (2026)

Обновлено: 2026-10-06 (pre-flight + gap scan старого черновика §0.4).
Источник: spine + LOCKED §0.1 + Cortex §0.2 + code audit §0.3 +
старый draft §0.4 + Zep/Graphiti/Letta/Mem0 + Anthropic Canon + ADR 0002.
Статус: **M0–M8 DONE** (2026-10-06). Cognee struck until ADR.
Решения §0.1 LOCKED; blockers §0.3 — по волнам.

Связанные: [global-retention.md](./global-retention.md), [mcp-roadmap.md](./mcp-roadmap.md),
ADR [0003](../../docs/adr/0003-postgres-checkpointer-session-ttl.md),
ADR [0004](../../docs/adr/0004-hybrid-memory-not-neo4j-only.md).

---

## 0. Вердикт

| Вердикт | Почему |
|---|---|
| **Эволюция spine → «живой» long-term cortex** | Medium остаётся Postgres; «бог-уровень» — bi-temporal Neo4j + durable jobs + ranking + rename extract |
| **Не Neo4j-only «революция»** | Ломает RLS/FTS/4096 embeddings/retention уже в проде; противоречит 060 и вашим же ответам §0.1 |
| **Не greenfield `memory_system/` / Qdrant / Celery DreamDaemon** | 050, 025, ADR 0002 |
| **Бог ≠ сложность ради слогана** | Big Tech 2026: scoped store + JIT + sleep-time extract + gated graph abstraction + evals |

**Формула «уровня бог» для Palatium:**  
`Postgres medium (hybrid+RLS) + SKIP LOCKED extract + bi-temporal Neo4j long-term + CronJob promote/decay + HITL + evals`  
— не «одна графовая БД вместо всего».

---

## 0.1 LOCKED решения владельца (2026-10-06)

| # | Решение | Следствие |
|---|---|---|
| 1 | **PostgresSaver + retention policy** для short-term TTL | Wave M1; ADR 0003; правка формулировки 060 «Redis» → checkpointer Postgres + retention class `checkpointer` |
| 2 | **Postgres `SKIP LOCKED`** для extract queue | Wave M3; без Redis-queue и без Temporal сейчас |
| 3 | **Cognee вычеркнуть** до отдельного ADR | Убрать из project-map / ТЗ как implied runtime; Neo4j promote = long-term SoT |
| 4 | **Rename `consolidate_memory` сейчас** | Wave M0b: → `extract_transcript_memories` (**hard cut**, без alias) |

---

## 0.2 Разбор предложения «Cortex» (bi-temporal Neo4j-only)

Контрпредложение требует «перерождения» и единого Neo4j SoT для L3+L4+L7.
Ниже — что **берём** и что **режем**. Чат не отменяет 060 (005); смена SoT =
отдельный ADR + правка правила, не «революция в плане».

### Принимаем (это и есть подъём до «кортекса»)

| Идея Cortex | Куда в плане |
|---|---|
| Bi-temporal поля на фактах (`valid_at`/`invalid_at` + system `created_at`/`expired_at`) | Wave **M5**: схема Neo4j `MemoryFact` / edges; вопросы «что знали тогда» |
| Abstraction Episode→Fact вместо «тупого копирования строк» | Уже extract→medium→promote; M5 уточняет: promote = абстракция + bi-temporal supersede |
| Hybrid recall: vector + graph traversal + lexical | Medium: pgvector+FTS; long: Neo4j vector index + path; fusion в recall policy |
| Reconsolidation / bump_access при recall | Уже; усилить в M2 |
| Out-of-band consolidation jobs (не `asyncio` в API) | M3 + promote CronJob (как retention ADR 0002) |
| Trust / confidence на фактах графа | M5: поля confidence; Beta-Bernoulli — M8 если eval просит |
| Hebbian weight на рёбрах как **batch** в promote job | M5/M8; не hot-path |
| Conflict → `invalid_at` на старом факте | M5: **policy + HITL** при низкой confidence / PII / contradiction class; не silent auto |

### Отвергаем

| Идея Cortex | Почему |
|---|---|
| Neo4j = единый SoT вместо `memory.entries` | Теряем FORCE RLS, Postgres FTS, native 4096 embed path, retention SECURITY DEFINER, уже написанный spine; latency/cost graph write на каждый turn |
| «Удалить старое / чистый лист» | Анти-production; данные и тесты уже на Postgres |
| L2 = Redis checkpointer | **Противоречит LOCKED #1** (PostgresSaver + retention) |
| Celery для DreamDaemon | ADR 0002 отверг Celery Beat; CronJob / compose one-shot |
| Langfuse как обязательный второй SoT observability | OTel + `palatium_*` (040); Langfuse — optional later, не блокер |
| Называть lexical «BM25» | Запрет 060 |
| MEMORY.md/USER.md в runtime system prompt продукта | Dev-time Cursor only; product core = structured memory + policies |
| Auto-resolve всех конфликтов | 020 HITL для high-risk / PII / irreversible semantic flips |
| Отдельный MCP `MemoryManager` server | Закрытый перечень 070 |
| Graphiti как default SoT | Optional adapter уже есть; default `postgres` (LOCKED) |

### Почему «единый граф» — не Big Tech 2026 default

MS Copilot / enterprise assistants держат **оперативную/эпизодическую** память в
документо-ориентированном store с ACL; граф — для **дистиллированных** связей.
Google ADK: durable schemas + dormancy, не «всё в KG». Anthropic: session log
вне окна + JIT retrieval. Bi-temporal KG (в духе Graphiti/Zep) — сила **long-term
слоя**, не замена medium ACL store.

У нас уже есть `GraphitiMemoryPort` как optional — он вдохновляет схему M5, но
**не** становится SoT без отдельного ADR (и LOCKED default = postgres).

---

## 0.3 Pre-flight audit (2026-10-06) — обязательно до кода

Сверка плана с кодом + индустрией (Zep/Graphiti bi-temporal, Letta sleep-time,
Mem0 extract-at-write, Anthropic session≠context). Вердикт: **spine готов как
фундамент; «живая когнитивная инфраструктура» = закрытый цикл ниже, не новый пакет.**

### Соответствие слогану «учится / забывает / консолидируется / перестраивается»

| Глагол | Индустрия 2026 | Palatium target | Код сейчас | Волна |
|---|---|---|---|---|
| **Учится** | sleep-time extract (Letta); distill on write (Mem0) | transcript → Keeper → medium off hot-path | asyncio queue; drop@256 | **M3** |
| **Забывает** | invalidate > silent hard-wipe; retention | TTL medium + soft/invalid graph; forget fan-out | hard DELETE medium only; Neo4j orphan after forget | **M1+M5+retention W4** |
| **Консолидируется** | sleep-time / batch abstraction | extract job ≠ promote CronJob | extract worker **calls promote** (`_maybe_promote`) | **M3 decouple** |
| **Перестраивается** | bi-temporal supersede (Zep); no overwrite truth | `invalid_at` + new fact; HITL high-risk | Neo4j ON MATCH overwrites `text` | **M5** |

### BLOCKER / GAP перед стартом волн

| # | Находка | Severity | Что сделать |
|---|---|---|---|
| B1 | 060/099/**000**/ТЗ ещё говорят Redis checkpointer + Cognee runtime | **CLOSED (M0)** | Нормы синхронизированы 2026-10-06 |
| B2 | `RETENTION_CHECKPOINT_DAYS=30` ≠ обещанные `session_ttl_seconds=1800` | **DONE M1** | Dual TTL: hot `MEMORY_SESSION_TTL_SECONDS` + cold `RETENTION_CHECKPOINT_DAYS`; cutoff = min |
| B3 | Extract worker → `_maybe_promote` смешивает оси | **DONE M3** | Promote только `jobs/memory_promote.py` |
| B4 | `ContextBuilder._persist_preserved` → прямой `MemoryPort.put` без secret/PII/MCP | **DONE M4** | `MemoryWriteService` (scan+PII+audit); compact без interactive HITL |
| B5 | Forget medium не трогает Neo4j; promote silent overwrite | **DONE (M5)** | forget → `expire_fact`; supersede + `GraphFactPolicy` |
| B6 | Hybrid merge без search-time `compute_importance` / RRF config | **DONE M2** | RRF/weighted + search-time importance |
| B7 | `MEMORY_BACKEND=mem0\|graphiti` wireable | **OPS risk** | staging/prod profiles force `postgres`; misconfig = fail-closed warn |
| B8 | Rename blast radius ~25+ sites | **M0b size** | hard cut (default); один PR только rename |

### Индустриальный вердикт (не меняет LOCKED)

- **Zep/Graphiti:** bi-temporal на **long-term** — да (M5); как единственный store — нет (ADR 0004).
- **Letta sleep-time:** отдельный фон от hot-path — да (M3 queue + CronJob promote).
- **Mem0:** extract facts — у нас MemoryKeeper; не тащить Mem0 SaaS как SoT.
- **«God» = closed loop + evals**, не Hebbian/FSRS в hot-path и не Neo4j-only.

### GO критерий реализации

Код волн стартует только после:

1. M0: 060 + 099 + ТЗ sync (Postgres short-term, Cognee struck); ADR 0003
   `accepted` после M1; ADR 0004 `accepted` после M5.
2. Явный выбор rename: **hard cut** (зафиксировано pre-flight; внешних MCP-клиентов нет в репо).
3. Каждая волна — отдельный PR; M3 включает decouple promote; M1 включает dual TTL.

---

## 0.4 Разбор старого черновика «живая когнитивная инфраструктура» (gap scan)

Полный текст черновика (7 слоёв + 12 алгоритмов + MCP + Istio + RAGAS).
Ниже — что **уже в плане**, что **добавляем**, что **осознанно не берём**.
Маркетинговые цифры (21.6% F1, +37% sleep, AUC 0.533→0.797, 98.7% tokens,
95% pilots) — **не контрактные SLO** без своего бенчмарка (как в ТЗ §15).

### Уже учтено (не дублировать)

| Черновик | Где у нас |
|---|---|
| Context window ≠ память; Lost-in-Middle / cost | 065 JIT + budgeted recall; M2 ranking |
| Durable schemas (не raw JSON dump) | Pydantic ports + `memory.entries` + pins 070 |
| Sleep consolidation REM/SWS/SHY | M3 extract + CronJob promote (не idle DreamDaemon) |
| Multi-agent / не God Agent | 000/030 registry |
| Context Engineering Write/Select/Compress/Isolate | save/search/compact/subagent (065); усилить §3 |
| Forgetting policy обязательна | retention + dual TTL + M5 invalidate |
| Reconsolidation on recall | `bump_access` + M2 |
| Hybrid retrieval + RRF/rerank | M2 (pgvector+FTS; не «BM25» naming) |
| Bi-temporal / temporal queries | M5 (Zep-класс на Neo4j LT) |
| HITL / PII / audit / OTel | 020/040; не sqlite audit |
| Progressive disclosure tools/skills | 065/070; skills M6 |
| Closed MCP remember/recall/forget/extract | platform tools (rename M0b) |
| Recall@k / p95 latency | M7 |

### Добавляем в план (реальные пробелы)

| # | Идея черновика | Решение | Волна |
|---|---|---|---|
| G1 | **5 failure modes** как design gates | DoD/evals: Knowledge Loss, Context Degradation, Silent Memory Death, Error Compounding, Storage Exhaustion | **DONE M7** |
| G2 | **Memory OS: Write / Select / Compress / Isolate** | Явный контракт в принципах: Write=MCP save/extract; Select=recall policy; Compress=ContextBuilder.compact+gated persist; Isolate=subagent condensed return (не dump) | §3 + M4 |
| G3 | **Hot / Warm / Cold** для эпизодов | Не отдельный Qdrant tier: importance+access → promote (hot→LT); low-access → compress/summarize medium или earlier expire (cold); warm = default medium TTL | M2 scoring + M5 + retention |
| G4 | **Provenance / lineage / sensitivity** | Сейчас: `contains_pii`, namespaces, source в promote частично. Добавить явные provenance fields на medium/graph (source_type, lineage ids) без god-schema на все 7 scopes | M5 (+ optional medium column migration) |
| G5 | **Dormancy / event-driven wake** | Не idle-polling daemon: extract/promote = CronJob + enqueue-on-turn (event). Agent «dormant» = checkpointer persist + wake on next HTTP/HITL resume (уже LangGraph interrupt). Отдельный DormancyGate класс — **не нужен** | уточнение M1/M3 |
| G6 | **MAGMA-lite** (semantic/temporal/entity; causal later) | M5: entity+fact+temporal; отдельный causal graph — M8 если eval | M5 / M8 |
| G7 | **RAGAS / Faithfulness / Hallucination** рядом с Recall@k | deterministic faithfulness + context_precision@k offline; LLM-judge optional non-CI | **DONE M7** |
| G8 | **Token cost per recall** | budget `recall_max_*` + G1 context degradation eval | **DONE M2/M7** |
| G9 | **Skill curator** (dedupe/устаревшие skills) | duplicate-name warn + keep-first; no autonomous skill-write | **DONE lite M6** |
| G10 | **EDMS / юридические документы / FTS кодексов** | Вне memory spine → 092 / knowledge schema; не Wave M* | out of scope |

### Отвергаем / не поднимаем в M0–M5

| Идея | Почему |
|---|---|
| Qdrant + Redis STM + SQLite FTS5 + parallel `memory-system/` | SoT Postgres; LOCKED |
| 12 алгоритмов обязательным checklist | Eval-gated M8; иначе complexity theatre |
| Emotional valence required on write | Optional metadata M8 |
| Auto conflict resolve + auto Core MEMORY.md update | 020 HITL; IDE files ≠ product |
| Hermes 8 external providers as product path | Optional Mem0/Graphiti only; default postgres |
| SPIFFE/SPIRE, Istio Ambient, RFC 8707 в memory PR | Platform mesh backlog; не блокер memory DoD |
| Regex PII lists в MemorySanitizer | Уже `domain/memory/pii.py`; phrase-lists 055 |
| `asyncio.create_task(DreamDaemon)` / idle 30m | ADR 0002; CronJob |
| Цифры 21.6%/176%/+37% как SLO | Только после собственного eval |

---

## 1. Проблема

Довести spine до **закрытого когнитивного цикла** (learn → forget → consolidate →
rebuild) на hybrid SoT: durable extract, session TTL, search-time importance,
bi-temporal graph, честное имя extract-tool — без сноса Postgres medium.

---

## 2. Целевая модель (7 слоёв → Palatium Cortex)

| Слой | Palatium | Технология (LOCKED) |
|---|---|---|
| L1 Working | `AgentState` + scratchpad | in-process state only |
| L2 Short-term | LangGraph **Postgres** checkpointer + dialog turns | PostgresSaver; TTL = retention `checkpointer` + `session_ttl_seconds` |
| L3 Episodic / medium | `memory.entries` | pgvector 4096 + FTS + FORCE RLS |
| L4 Semantic / long-term | Neo4j facts/entities **bi-temporal** | только через promote/abstraction |
| L5 Procedural | Skills progressive disclosure | DONE M6 (`skills/procedural` + `skill_reference`); не medium DB |
| L6 Core identity | structured prefs/facts + (opt) IDE MEMORY.md | не файлы как product SoT |
| L7 Cross-context | namespaces + `graph_query` multi-hop / temporal | Neo4j bi-temporal queries |
| «Dream» REM | sleep-time extract | `SKIP LOCKED` job table → MemoryKeeper |
| «Dream» SWS/SHY | promote + hebbian batch + conflict policy | CronJob `MemoryPromotionService` |

Оси:

- **extract** = transcript → medium (MCP tool после rename: `extract_transcript_memories`).
- **promote / abstract** = medium → bi-temporal graph (batch; не agent hot-path).

---

## 3. Принципы

1. **One SoT per tier** — L2/L3 Postgres; L4/L7 Neo4j; не схлопывать.
2. **Brain ≠ hands ≠ session** — Anthropic Managed Agents.
3. **Memory OS (Write / Select / Compress / Isolate)** — Write только gated MCP/service;
   Select = budgeted recall + importance; Compress = compact + persist goal/plan;
   Isolate = subagent condensed return (065). Сырой dump истории запрещён.
4. **JIT + budget** — `recall_for_thread` + search-time importance; защита от
   Lost-in-Middle / context pollution / token explosion.
5. **Privacy by construction** — RLS, PII, secret scan, HITL (020/060).
6. **Forgetting is a feature** — dual TTL + retention + graph invalidate; иначе
   Storage Exhaustion / Silent Memory Death.
7. **Eval-gated complexity** — FSRS/Hebbian/Bayesian/emotional не в M1–M4.
8. **Out-of-band jobs** — SKIP LOCKED + CronJob; event enqueue; не idle DreamDaemon.
9. **Closed tool surface** — 070; rename = правка перечня, не второй tool рядом.
10. **Failure-mode DoD** — Knowledge Loss / Context Degradation / Silent Death /
    Error Compounding / Storage Exhaustion покрыты тестом или метрикой (G1).

---

## 4. Scope / вне scope

### В scope

- M0 norm sync (060/099/ТЗ) + M0b **rename** (070 hard cut).
- M1 Postgres checkpointer + **dual TTL** (`session_ttl_seconds` + cold `checkpoint_days`).
- M2 search-time importance + RRF config.
- M3 durable extract (`SKIP LOCKED`) + **decouple promote** из extract worker.
- M4 compaction через gated writer (secret/PII/audit).
- M5 bi-temporal Neo4j + supersede + forget fan-out + conflict policy (ADR 0004).
- M7 evals/SLO; global-retention Neo4j fact (W4).
- Closed-loop invariants §0.3 (learn/forget/consolidate/rebuild).

### Вне scope

- Neo4j-only medium; Qdrant; `memory_system/`; Celery DreamDaemon.
- Graphiti/Mem0 as production default.
- Cognee до нового ADR.
- FSRS cards / обязательный emotional_valence.
- Langfuse как обязательный dependency.
- Autonomous SKILL.md writes из диалога.
- Learning Agent.

---

## 5. Baseline (2026-10-06)

| Capability | Статус |
|---|---|
| Medium + hybrid + RLS | DONE |
| MCP memory tools + HITL | DONE (`consolidate_memory` → rename M0b) |
| Extract + MemoryKeeper | DONE (SKIP LOCKED queue) |
| Promote → Neo4j | DONE (bi-temporal supersede — M5) |
| Importance domain formula | DONE (promote + search-time) |
| Retention medium/episode/PII | DONE |
| Budgeted recall | DONE |
| Postgres checkpointer path | DONE (staging/prod default on; MemorySaver = development) |
| `session_ttl_seconds` | DONE (dual TTL + retention job) |
| Extract queue | DONE (SKIP LOCKED + DLQ; promote decoupled) |
| Search-time importance / RRF | DONE |
| Compaction persist | DONE (`MemoryWriteService` gated) |
| Bi-temporal / supersede | DONE (M5) |
| Forget → graph fan-out | DONE (M5) |
| Cognee | **STRUCK** until ADR |
| Neo4j fact retention | GAP (global-retention W4) |

---

## 6. Волны

### Wave M0 — Spec freeze / norm sync — **DONE** (2026-10-06)

- [x] План + Cortex + pre-flight + draft gap; ссылка в `docs/README.md`.
- [x] **060**: hybrid cortex, dual TTL, Memory OS, extract⊥promote, compact→medium.
- [x] **000-architecture**: Postgres checkpointer; out-of-band jobs; memory infra.
- [x] **099 / max-pro-level-tz**: Cognee/Qdrant/LangMem-as-SoT struck; hybrid cortex.
- [x] ADR 0003 context обновлён (норма synced; код dual TTL → M1); 0004 `proposed` до M5.
- [x] Companion: `agent-refactoring` skill/reference — LangMem+Cognee не SoT.

**DoD:** `rg` rules/TZ: нет Redis-as-checkpointer / Cognee-as-runtime SoT. ✅

---

### Wave M0b — Rename MCP extract tool (LOCKED #4) — **DONE** (2026-10-06)

**Имя (канон):** `extract_transcript_memories`  
**Было:** `consolidate_memory`.  
**Compat:** hard cut (API `POST /api/memory/extract`, HITL `mem-extract-*`).

- [x] schemas + pin fingerprint + discovery
- [x] handler / stub / namespace policy / HITL / router
- [x] rules 070/020/060 + hooks/permissions
- [x] tests + ops-readiness / production-audit / TZ tool list

**DoD:** production grep `consolidate_memory` = 0 (кроме plan history). ✅

---

### Wave M1 — Short-term: PostgresSaver + dual TTL (LOCKED #1) — **DONE** (2026-10-06)

1. Default staging/prod: Postgres checkpointer on; `MemorySaver` только development.
2. `MemoryConfig.session_ttl_seconds` (default 1800) — **hot** inactivity window.
3. `RetentionConfig.checkpoint_days` — **cold** upper bound (defense-in-depth).
4. Checkpointer retention job: cutoff = `now - min(hot, cold)` на `sessions.updated_at`.
5. Dialog turns отдельно; Redis только HITL/kill-switch/cache.
6. 060 уже synced в M0.

**DoD:**

- [x] Dual TTL в конфиге; unit resume/expire cutoff.
- [x] ADR 0003 → `accepted`.
- [x] Семантика CronJob vs native EXPIRE задокументирована в ADR 0003.

---

### Wave M2 — Retrieval quality — **DONE** (2026-10-06)

1. Search-time `compute_importance` после hybrid merge (`rank_by_search_importance`).
2. RRF `k` из конфига (`MEMORY_HYBRID_FUSION` / `MEMORY_RRF_K`; default rrf/60).
3. Embedding rerank остаётся opt-in.
4. `bump_access` = reconsolidation on recall (уже; комментарий зафиксирован).

**DoD:**

- [x] Unit ranking (RRF + search-time importance).
- [x] Spine eval / recall path unchanged (budget + bump).
- [x] Perf nightly still uses `merge_hybrid_scores` adapter.

---

### Wave M3 — Durable extract: `SKIP LOCKED` + axis split (LOCKED #2) — **DONE** (2026-10-06)

1. Job table `memory.extract_jobs` + `FOR UPDATE SKIP LOCKED`; `asyncio.Queue` убран.
2. Idempotent enqueue `(thread_id, task_id)` + lease reclaim + DLQ `dead`; metrics depth/lag.
3. **Удалён** `_maybe_promote` — promote только `python -m palatium_ai.jobs.memory_promote`.
4. Extract = REM only; promote = CronJob/one-shot.
5. Не Celery.

**DoD:**

- [x] Lease expiry → redelivery same job id (no dup row).
- [x] Promote отсутствует на extract path (тест).
- [x] Queue depth/lag/DLQ gauges в 040.

---

### Wave M4 — Compaction ↔ gated memory write — **DONE** (2026-10-06)

1. `MemoryWriteService` (scan + PII + audit + put); ContextBuilder compact
   persist только через него. EXCEPTION (020): system compact без interactive
   HITL; user `save_memory` остаётся HITL (`MemorySaveService`).
2. Regression: long dialog → compact → build goal/plan/last_results.
3. Secret-shaped preserve keys rejected (fail-closed).

**DoD:**

- [x] Нет unscoped `MemoryPort.put` из ContextBuilder.
- [x] Tests: persist + scan rejection.

---

### Wave M5 — Bi-temporal long-term cortex (принятая часть Cortex) — DONE

1. Neo4j: `valid_at` / `invalid_at` / `created_at` / `expired_at` + confidence.
2. Promote = abstraction + **supersede** (не silent `SET text`); contradiction
   policy + HITL high-risk/PII (`GraphFactPolicy` / `blocked_pii`).
3. Forget/TTL medium → fan-out `expired_at` на linked `MemoryFact`
   (`forget_memory` → `GraphWritePort.expire_fact`).
4. Temporal `graph_query` (`$as_of` + `ACTIVE_FACT_AS_OF_PREDICATE`); PG lexical остаётся.
5. Provenance/lineage/source_type на graph facts (G4); medium — минимально
   необходимое без god-schema.
6. Hot/Warm/Cold (G3): promote = hot path to LT; cold = low importance →
   earlier expire / summarize; не отдельный vector DB.
7. MAGMA-lite: entity + fact + temporal; causal graph — не в этой волне.
8. Hebbian edge bump только в promote batch (deferred if unused).
9. Prod: `GRAPH_QUERY_BACKEND=neo4j`; `MEMORY_BACKEND=postgres`.

**DoD:** ✅ temporal query test; ✅ no silent overwrite; ✅ forget fan-out test;
✅ ADR 0004 accepted.

---

### Wave M6 — Procedural / IDE core — DONE

1. JIT `skill_catalog` (name+description) + MCP `skill_reference` (reference.md / body).
2. Product skills under `skills/procedural/`; closed tool list 070 updated.
3. `.agent/MEMORY.md` — Cursor DX only (not product SoT / not runtime load).
4. G9 lite: duplicate skill names → keep first + warn (no autonomous skill-write).

---

### Wave M7 — Evals / SLO (+ failure modes G1/G7/G8) — DONE

| Metric | Target | Status |
|---|---|---|
| Recall@k (spine eval) | > 0.85 | ✅ `tests/eval/test_memory_failure_modes_m7.py` + Gauge |
| Query p95 | < 200 ms (nightly) | ✅ already `PalatiumMemoryQueryLatencyHigh` |
| Faithfulness / context precision (optional LLM-judge) | ≥ 0.85 / ≥ 0.80 — **не** hard CI | ✅ deterministic G7 lite in eval; LLM-judge remains optional |
| Token / char budget on recall | within `recall_max_*` | ✅ G1 context degradation + spine |
| Extract DLQ / promote errors | alert | ✅ `PalatiumMemoryExtractDeadLetter` / `PalatiumMemoryPromoteErrors` |
| Failure modes G1 | regression tests or metrics for each | ✅ five gates in M7 eval |

Production-audit memory section updated (bi-temporal / fan-out / Recall@k).

---

### Wave M8 — Eval-gated advanced — DONE (2026-10-06)

Cross-encoder wrap (`MEMORY_CROSS_ENCODER_RERANK`); binary quantize helpers
(`domain/memory/binary_quantize`, flag reserved until `bit(4096)` migration);
τ-decay (`MEMORY_IMPORTANCE_HALF_LIFE_DAYS`); xMemory decouple; Bayesian α/β;
Hebbian edge bump; optional `emotional_valence` on save. All flags **OFF** by
default. **Cognee** — только после нового ADR (struck).

---

## 7. Явные rejects (черновик + Cortex)

| Идея | Решение | Основание |
|---|---|---|
| Neo4j-only SoT / миграция «всё из memory.entries» | **Reject** | ADR 0004, 060, LOCKED #1–2 |
| Qdrant / parallel `memory_system/` | Reject | 060, 050 |
| Celery DreamDaemon | Reject | ADR 0002 |
| Redis checkpointer | Reject | LOCKED #1 |
| Auto conflict without HITL | Reject for high-risk | 020 |
| `consolidate_memory` name | **Replace now** | LOCKED #4, 070 |
| Cognee implied | **Struck** | LOCKED #3 |
| Langfuse required | Defer | 040 OTel SoT |
| «BM25» naming | Forbidden | 060 |
| God singleton MemoryManager | Reject | 000 DI |

---

## 8. Enforcement

| Гейт | Где |
|---|---|
| Hybrid SoT (no Neo4j-only) | ADR 0004 + ревью |
| RLS | migrations + tests |
| MCP pin fingerprints after rename | tool_policy tests |
| TODO → `plans/memory-max-pro.md §N` | check_todos.py |
| Evals / perf | tests/eval, tests/perf |
| No Celery for memory jobs | ADR 0002 |

---

## 9. Definition of Done («живая» память)

1. **Учится:** durable extract off hot-path; tool = `extract_transcript_memories`.
2. **Забывает:** medium TTL/forget + graph `expired_at`/`invalid_at` fan-out;
   dual session TTL честный.
3. **Консолидируется:** extract ⊥ promote (разные jobs); оси не смешаны.
4. **Перестраивается:** bi-temporal supersede; temporal queries; HITL high-risk.
5. Medium hybrid + search-time importance + RLS + gated compaction writes.
6. Evals Recall@k / p95; metrics 040; no Cognee/Qdrant/`memory_system/`; 060 sync.

---

## 10. Открытые вопросы — CLOSED

| # | Решение |
|---|---|
| Checkpointer | Postgres + dual TTL |
| Queue | SKIP LOCKED |
| Cognee | Struck until ADR |
| Rename | **hard cut** → `extract_transcript_memories` |
| Neo4j-only Cortex | Rejected (ADR 0004); bi-temporal on long-term accepted |

---

## 11. Порядок старта (после pre-flight)

```text
M0 (norm sync 060/099/TZ) → M0b (rename hard cut) → M1 (dual TTL)
  → M2 (ranking) → M3 (SKIP LOCKED + decouple promote) → M4 (gated compact)
  → M5 (bi-temporal + forget fan-out) → M7 (evals) → M6/M8 optional
```

**M0 + M0b DONE — следующий M1** (Postgres checkpointer + dual TTL).

---

## 12. Карта предложений → действие

| Источник | Действие |
|---|---|
| 7-layer + Qdrant draft | Reject package |
| Cortex Neo4j-only | Reject SoT; take bi-temporal/jobs |
| Pre-flight audit | B1–B8 → усиленные DoD волн |
| Industry (Zep/Letta/Mem0) | Confirm hybrid + sleep-time + bi-temporal LT |

---

**Итог:** идеальное «бог»-решение 2026 для Palatium — **закрытый когнитивный цикл
на hybrid cortex** (Postgres medium + sleep-time extract + CronJob promote +
bi-temporal Neo4j + HITL + evals). Полный рефакторинг = волны M0→M5 по осям,
не снос SoT. Pre-flight: **GO после M0 norm sync**; первый код — M0b.

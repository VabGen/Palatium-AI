# План: Context · Dialog · Memory 2026 (post–Memory MAX PRO)

Обновлено: 2026-11-03.  
Статус: **accepted** (план принят владельцем 2026-11-03; CMD0–CMD1 в работе на `dev`).  
База: [memory-max-pro.md](./memory-max-pro.md) (M0–M8 DONE), ADR [0003](../../docs/adr/0003-postgres-checkpointer-session-ttl.md), ADR [0004](../../docs/adr/0004-hybrid-memory-not-neo4j-only.md), ADR [0008](../../docs/adr/0008-memory-origin-trust-ceiling.md) (**proposed**, обязателен до prod flag), правила **060 / 065 / 070 / 020**.

Связанные: [mcp-roadmap.md](./mcp-roadmap.md), [evolution-to-big-tech.md](./evolution-to-big-tech.md), `.cursor/rules/evolution-to-big-tech.mdc`.

---

## 0. Вердикт и границы

| Вердикт | Почему |
|---|---|
| **Эволюция поверх hybrid cortex**, не greenfield | Spine уже закрывает learn/forget/consolidate/rebuild (M0–M8). Пробелы — context assembly, observability памяти, ASI-06 на extract→promote, procedural self-improve, project context files |
| **SoT не меняется** | Short = Postgres checkpointer (ADR 0003); medium = `memory.entries` pgvector+FTS+RLS; long = Neo4j **только через promote** (ADR 0004) |
| **Hermes** | `DOC_ONLY`. Паттерны (bounded curation, progressive disclosure, prompt-cache tiers) переносим **в контракты Palatium**, не как зависимость `nousresearch/hermes-agent` и не как file-SoT `MEMORY.md` |

### Жёсткие rejects (не обсуждаются в этом плане)

| Идея | Статус |
|---|---|
| Hermes file-SoT (`MEMORY.md` / `USER.md` как product runtime) | **Reject** (memory-max-pro §0.2 / L6) |
| Neo4j-only medium | **Reject** (ADR 0004) |
| Qdrant / parallel `memory_system/` | **Reject** (060) |
| Redis checkpointer | **Reject** (ADR 0003) |
| Расширение 070 без правки правила + pin + schema | **Reject** (070, 050) |

### Скоуп этого плана (волны **CMD0–CMD4**)

1. Prompt-cache tiers: `stable → context → volatile`.
2. Memory-as-tools: `explain_belief`, `memory_audit`, `memory_verify` (+ правка 070).
3. ASI-06 для sleep-time extract: origin ceiling + staged promotion **без** убийства автоматизации.
4. Self-authored skills (снятие «вне scope» M6 G9): HITL + lint + lock product skills.
5. Runtime `AGENTS.md` (project context) без Hermes auto-discovery.

### Вне scope

- Смена embedding dim / reindex; binary HNSW cutover.
- A2A (Google) protocol adapter.
- Autonomous skill-write **без** HITL.
- Mem0/Graphiti как production default.
- Переписывание ContextEnricher/Intent осей (055) — только если eval покажет регрессию continuity.

---

## 1. Матрица текущего состояния (этап 1 → зафиксировано)

| Слой / компонент | Якорь | Вердикт | Комментарий |
|---|---|---|---|
| Working (L1) | `scratchpad.py`, `AgentState` | OK | |
| Short-term / dialog (L2) | checkpointer + `dialog_turn_store.py`, ADR 0003 | OK | Dual TTL |
| Medium (L3) | `postgres_memory_port.py`, `MemoryType` | OK | Hybrid + RLS |
| Long-term (L4) | `memory_promotion.py`, Neo4j | OK | Promote-only |
| Procedural (L5) | `skills/procedural/*`, `skill_reference` + HITL `skill_manage` | OK* | *flag `ALLOW_SELF_AUTHORED_SKILLS=false` до soak |
| JIT context | `ContextBuilder` | OK | Selective keys |
| Compaction | `compact()` + `MemoryWriteService` | OK | |
| Budgets | `budget.py`, `recall_max_*` | OK | |
| Recall | `recall_for_thread`, deferred mid-graph | OK | Origin ceiling + identity pins |
| Prompt-cache tiers | `PromptAssemblyPolicy` + harness metrics | OK | Provider `cache_*_tokens` → `palatium_prompt_cache_tokens_total` |
| User write HITL | `tool_policy` save/forget/extract pins | OK | |
| System extract write | origin/trust + inferred TTL + corroboration | OK | ADR 0008 proposed → accepted after staging soak |
| Memory-as-tools | explain/audit/verify + search/save/forget/extract | OK | verify HITL; owner-scoped audit |
| Hermes / AGENTS.md | `AGENTS.md` + `ProjectContextPort` | OK | DX `.agent/MEMORY.md` never runtime |
| Evals | `tests/eval/test_memory_*` + ASI-06 + identity pin | OK | Baseline + CMD gates |

---

## 2. Расхождения с эталонами 2026

Формат: эталон → что не так → файл+строка → что должно быть.

### 2.1 Anthropic — context engineering / dreaming

| # | Эталон | Gap | Доказательство | Целевое |
|---|---|---|---|---|
| A1 | Compaction + structured notes + multi-agent clean windows | **CLOSED** PromptAssembly tiers + identity pins | `domain/policies/prompt_assembly.py`, harness tier metrics | Держать; cache hit rate — provider tokens metric |
| A2 | Out-of-band “dreaming” curated | **CLOSED** origin/trust + corroborate→promote | ADR 0008 + `memory_consolidate` | Soak → ADR accepted |
| A3 | File-system memory as optional metaphor | Product SoT = DB (правильно) | `.agent/MEMORY.md` L1–9 DX-only | Сохранить; **не** грузить в runtime |

### 2.2 Hermes patterns (паттерны, не продукт)

| # | Эталон | Gap | Доказательство | Целевое |
|---|---|---|---|---|
| H1 | Bounded curation | Char/item budgets есть; нет «консолидируй или умри» на **profile** размере | `budget.py` memory_max_chars=800 на **inject**, не на store | Retention + promote + profile soft-cap (count/importance), не MEMORY.md 2200 |
| H2 | Progressive disclosure skills | **CLOSED** HITL `skill_manage` + product lock (flag off) | `skills/procedural/skills-lock.json`, CMD4 | Soak → flag on |
| H3 | Prompt-cache stability | **CLOSED** | tiers + `palatium_prompt_cache_tokens_total` | Наблюдать hit rate на staging |
| H4 | Session FTS | Есть Postgres FTS на medium + dialog store | Не SQLite FTS5 | Оставить Postgres; не тащить SQLite |

### 2.3 Microsoft Agent Framework

| # | Эталон | Gap | Доказательство | Целевое |
|---|---|---|---|---|
| M1 | Episodic / semantic / procedural layers | Слои есть (L2–L5) | ADR 0004 + M6 | Усилить контракты provenance между слоями |
| M2 | Recall under hard budget + resolved identity | Есть | `recall_for_thread`, namespaces | `explain_belief` должен возвращать тот же resolved identity |
| M3 | Pluggable providers | Optional mem0/graphiti | `MEMORY_BACKEND` | Prod force postgres (уже ops risk B7) — не менять |

### 2.4 OWASP ASI-06 Memory Poisoning

| # | Контроль | Сейчас | Gap |
|---|---|---|---|
| O1 | Validate before write | secret scan + PII + schema | OK на записи |
| O2 | Segment by origin / sensitivity | namespaces + PII sticky + `origin`/`trust` | **CLOSED** (ADR 0008) |
| O3 | Short retention for unverified | `RETENTION_MEMORY_INFERRED_DAYS` | **CLOSED** (default 7d + LEAST upsert) |
| O4 | Do not self-feed | ExtractAdmission + wrap_untrusted + corroboration job | **CLOSED** (batch upgrade; ceiling demotion) |
| O5 | Staged promotion | medium trust + promote gate | **CLOSED** (verified / inferred+freq; quarantined never) |

---

## 3. Целевая архитектура (инкремент)

### 3.1 Слои (без смены backend)

```
┌─────────────────────────────────────────────────────────────┐
│ PromptAssemblyPolicy (065)                                  │
│  stable  → identity + tool guidance + AGENTS.md rules       │
│  context → thread/user meta + skill_catalog (index only)    │
│  volatile→ recall hits + attachments + timestamp            │
└─────────────────────────────────────────────────────────────┘
         │ JIT keys only (ContextBuilder)
         ▼
 L1 scratchpad ──► L2 dialog+checkpointer ──► L3 medium
                                      │              │
                                      │              ├ origin=user_hitl | extract | compact | system
                                      │              ├ trust: verified | inferred | quarantined
                                      │              └ TTL by trust (inferred shorter)
                                      ▼
                               L4 Neo4j (promote only; trust≥verified OR high importance + policy)
 L5 procedural skills (catalog JIT + skill_reference; skill_manage HITL write)
```

### 3.2 Prompt assembly (целевое)

| Tier | Содержимое | Cache | Меняется |
|---|---|---|---|
| **stable** | Agent system prompt + RBAC tool summaries (names only) + optional `AGENTS.md` rules block | `cache_control=ephemeral` | Редко (деплой / смена skill pin) |
| **context** | `thread_id`, route axes, skill_catalog index, session privacy flags | Обычно не кэшировать отдельно | Per-thread / per-turn light |
| **volatile** | `memory_hits`, dialog window, attachment fences, wall-clock | Never cache as prefix | Каждый turn |

Реализация: `domain/policies/prompt_assembly.py` + тонкий helper в Harness/агентах — **не** второй ContextBuilder.

### 3.3 Memory write / ASI-06 (целевое)

| Источник | origin | trust при записи | Hot-path recall | Promote to L4 |
|---|---|---|---|---|
| User «запомни» + HITL | `user_hitl` | `verified` | Да (в т.ч. cross-thread prefs) | По порогам |
| Sleep-time extract | `extract` | `inferred` | Да, но **ниже** verified; min_confidence + origin demotion | Только после corroboration **или** access_frequency≥N **или** explicit user confirm |
| Context compact | `compact` | `inferred` | Thread-scoped | Редко / high importance |
| System ops | `system` | `verified` | По политике | По политике |

**Corroboration (без убийства автоматизации):**  
не HITL на каждый extract. Авто-upgrade `inferred → verified` когда: (a) тот же факт извлечён ≥2 независимых thread/turns (token-overlap policy уже есть), **или** (b) user later HITL-save overlaps, **или** (c) promote job + `GraphFactPolicy` + optional Bayesian trust (M8 flag).  
PII / contradiction / high-risk kind → HITL или `quarantined` (не в hot recall).

### 3.4 Memory-as-tools (целевое, 070)

Добавить в закрытый перечень (правка правила 070 + pins):

| Tool | Side effect | HITL | Назначение |
|---|---|---|---|
| `explain_belief` | read | no | Provenance: entry_key, origin, trust, namespace, scores, graph link if any |
| `memory_audit` | read | no* | Bounded list/filter by origin/trust/time (*manager ACL later; v1 = owner-scoped) |
| `memory_verify` | write | **yes** | Upgrade trust / confirm / quarantine; audit event |

Существующие `search_memory` / `save_memory` / `forget_memory` / `extract_transcript_memories` **не** переименовывать.

### 3.5 Skills self-author (целевое)

- Новый MCP `skill_manage` (write, HITL, irreversible=false, risk=high).
- Payload: name, description, body/reference; lint: frontmatter schema, safe name, max size, secret scan, no path escape.
- Persist under `skills/procedural/<name>/` **или** tenant-scoped store (решение §6 Q1); v1 = filesystem + product lock file.
- Progressive disclosure без изменений: catalog = summary; body via `skill_reference`.
- `skills/procedural/skills-lock.json` — hash + version; DX `skills-lock.json` в корне **не** смешивать.

### 3.6 AGENTS.md (целевое, без Hermes)

- Файл в корне репо: `AGENTS.md` — **project operating contract** (как OpenAI/агентные IDE 2026), не identity пользователя.
- Runtime: `ProjectContextPort` читает allowlisted paths (`AGENTS.md` only в v1), inject в **stable** tier через JIT key `project_agents_md` (только агентам, у которых ключ в `get_required_context_keys()`).
- Не грузить `.agent/MEMORY.md`, `.cursorrules`, чужие skill trees.
- Размер: hard cap (напр. 4–8k chars) + hash в метриках; изменение файла = cache bust stable prefix.

---

## 4. План миграции по фазам

Общая нумерация волн: **CMD0…CMD4**. Один PR ≈ одна подволна. Target PR base = `dev`.

---

### Фаза 0 — CMD0: Измеримость и контракты — **DONE 2026-11-03** (на `dev`, без коммита)

| Шаг | Содержание | Файлы | DoD | Риск | Откат |
|---|---|---|---|---|---|
| CMD0.1 | Зафиксировать матрицу §1 в плане + ссылка из `docs/README.md` | этот файл; `docs/README.md` | Индекс docs содержит строку на план | Низкий | Удалить строку индекса |
| CMD0.2 | Golden fixtures: prompt tier labels + origin/trust absent today | `tests/eval/fixtures/memory_cmd/` (новый), расширить `test_memory_failure_modes_m7.py` маркерами «expected gap» | Eval краснеет только на **регрессию** существующих метрик; новые asserts в `xfail`/`strict=False` до CMD1 | Низкий | Удалить fixtures |
| CMD0.3 | Метрики-заготовки (no-op counters) | `core/observability/metrics.py` (+040 если новые имена) | Имена согласованы с 040; нули в /metrics | Низкий | Feature-flag off |

**Стоимость/latency:** ≈0 на hot-path.

---

### Фаза 1 — CMD1: ASI-06 origin ceiling + staged trust — **DONE 2026-11-03** (код на `dev`; ADR 0008 остаётся `proposed` до staging soak)

| Шаг | Содержание | Файлы | DoD | Риск | Откат |
|---|---|---|---|---|---|
| CMD1.1 | Literal `MemoryOrigin`, `MemoryTrust` в `domain/memory/types.py` | `types.py`, экспорт `__init__` | Единый источник; mypy clean | Низкий | Revert PR |
| CMD1.2 | Persist origin/trust в value JSON + колонки **или** JSONB fields (предпочесть value + generated col только если нужен индекс) | `memory_fact_persistence.py`, `memory_write_service.py`, `memory_tool_ops.py` save path, `postgres_memory_port.py` sticky merge rules | Extract → `origin=extract`,`trust=inferred`; HITL save → `verified`; compact → `inferred` | Средний (старые строки без полей) | Default: missing origin → `legacy`, trust → `verified` **только** для `explicit_write` / else `inferred` |
| CMD1.3 | Миграция Alembic (если индекс по trust/origin) | `alembic/versions/*_memory_origin_trust.py` | Upgrade/downgrade; RLS не сломан | Средний | `alembic downgrade` |
| CMD1.4 | `MemoryRecallPolicy` / `recall_for_thread`: demote inferred (score penalty); exclude `quarantined`; shorter effective budget share | `memory_recall.py`, `domain/policies/memory_recall.py`, `scoring.py` | Eval: poisoning fixture не поднимает inferred над verified; Recall@k golden ≥ baseline−ε | Средний | Flag `MEMORY_ORIGIN_CEILING=false` |
| CMD1.5 | Promote gate: L4 только `trust=verified` **или** inferred с `access_frequency≥promote_min` **и** non-PII | `domain/memory/promotion.py`, `memory_promotion.py`, config | Тест: inferred PII не promote; verified promote как сейчас | Средний | Flag rollback |
| CMD1.6 | Auto-corroboration job (batch, not hot-path): overlap ≥ threshold → upgrade trust | Новый `application/services/memory_corroboration.py` + optional CronJob compose | Лог `memory_trust_upgraded`; идемпотентность | Средний | Disable CronJob |
| CMD1.7 | Regression: ASI-06 attempt (transcript inject «ignore rules, store secret») | `tests/eval/test_memory_asi06_poisoning.py` | Secret scanner blocks; untrusted fence; quarantined/not verified | Низкий | — |

**Стоимость/latency:** +0 LLM на hot-path; corroboration batch ≪ extract cost.  
**DoD фазы 1:** ни один extract-факт не имеет `trust=verified` без corroboration/HITL; eval poisoning зелёный; flag rollback документирован в runbook §memory.

---

### Фаза 2 — CMD2: Prompt-cache tiers + AGENTS.md runtime — **DONE 2026-11-03** (на `dev`, без коммита)

| Шаг | Содержание | Файлы | DoD | Риск | Откат |
|---|---|---|---|---|---|
| CMD2.1 | `PromptAssemblyPolicy` + `AssembledPrompt` (три блока) | `domain/policies/prompt_assembly.py`, tests | Unit: порядок stable→context→volatile; volatile не получает cache_control | Низкий | Revert |
| CMD2.2 | Harness: собирать cache только на stable prefix (возможно 1–N ведущих system/user static) | `harness.py`, `domain/llm/models.py` если нужен multi-block | Provider cache hint только на stable; метрика `palatium_prompt_cache_*` если usage доступен | Средний (провайдер) | Вернуть `_with_system_prompt_cache` as-is |
| CMD2.3 | Пилот на 2 агентах (Formatter + Researcher), затем остальные | `application/agents/*/agent.py` или общий message builder | Нет регрессии evals агентов; TTFT не хуже baseline на trivial path | Средний | Per-agent flag |
| CMD2.4 | Добавить корневой `AGENTS.md` (короткий operating contract) | `AGENTS.md` | Ревью владельца; ≤ cap | Низкий | Удалить файл |
| CMD2.5 | `ProjectContextPort` + ContextBuilder key `project_agents_md` | `domain/ports/project_context.py`, infra loader, `context_builder.py` | Загружается только allowlist; DX `.agent/MEMORY.md` **не** читается (тест) | Средний | Flag `PROJECT_AGENTS_MD=false` |
| CMD2.6 | JIT: ключ только у Supervisor/Intent/Researcher (явный список) | agent `get_required_context_keys` | Нет context dump всем узлам (065) | Низкий | Убрать ключ |

**Стоимость/latency:** цель — **снижение** prompt tokens via cache hits; AGENTS.md ≤8k chars один раз в stable.  
**DoD фазы 2:** документ политики + тесты порядка блоков; AGENTS.md в stable только у allowlisted агентов; evals без регрессии.

---

### Фаза 3 — CMD3: Memory-as-tools (explain / audit / verify) — **DONE 2026-11-03** (на `dev`; HITL verify + pin soak before treating as prod-hard)

| Шаг | Содержание | Файлы | DoD | Риск | Откат |
|---|---|---|---|---|---|
| CMD3.1 | Frozen I/O schemas | `domain/mcp/platform_schemas.py` | Schemas + fingerprints стабильны | Низкий | Revert |
| CMD3.2 | Pins + правка **070** перечень | `tool_policy.py`, `.cursor/rules/070-mcp-tools.mdc` | Три имени в правиле и pins; HITL на verify | Средний (процесс) | Не мержить правило без кода и наоборот |
| CMD3.3 | Ops: `memory_tool_ops.py` + handler branches | `memory_tool_ops.py`, `platform_tool_handler.py` | RBAC deny без allow-list; audit events | Средний | Disable tools via pin remove |
| CMD3.4 | ACL: добавить tools в `AgentConfig.allowed_tools` только Researcher (+ optional MemoryKeeper read-only explain) | `application/agents/*/config.py` | Supervisor **без** write verify | Низкий | Убрать из allow-list |
| CMD3.5 | `memory_verify` → trust upgrade/quarantine через gated write | services + HITL card type | Одноразовая карточка; idempotency | Средний | HITL reject path |
| CMD3.6 | E2E + unit | `tests/unit/test_platform_memory_mcp.py`, integration | explain возвращает origin/trust; verify без HITL → deny | Низкий | — |

**Стоимость/latency:** read tools дешёвые (1 DB); verify = HITL latency (ожидаемо).  
**DoD фазы 3:** 070 обновлён; три tool в pins; explain_belief совпадает с recall identity; ASI-06 eval использует verify path.

---

### Фаза 4 — CMD4: Self-authored skills (безопасный G9) — **DONE 2026-11-03** (код на `dev`; `ALLOW_SELF_AUTHORED_SKILLS=false` до staging soak; skills-lock warn-only в CI)

> **Снимает** «вне scope: Autonomous SKILL.md writes» из memory-max-pro §4 **только** в форме HITL-managed write. Подтверждение владельца: запрос на этот план 2026-11-03.

| Шаг | Содержание | Файлы | DoD | Риск | Откат |
|---|---|---|---|---|---|
| CMD4.1 | Спека lint: frontmatter, name regex, max body, ban shell/MCP escape patterns | `domain/skills/lint.py`, tests | Deterministic reject reasons | Низкий | — |
| CMD4.2 | Schema + pin `skill_manage` (write, HITL, high) | `platform_schemas.py`, `tool_policy.py`, **070** | Pin fingerprint match | Средний | Не включать в allow-list |
| CMD4.3 | `SkillCatalogPort.upsert` + filesystem impl + secret scan | `domain/skills/port.py`, `filesystem_skill_catalog.py` | Path confined to roots; restart/index invalidate documented | Высокий (FS write) | HITL-only + feature flag `SKILLS_SELF_AUTHOR=false` (default **false** до staging soak) |
| CMD4.4 | Product lock `skills/procedural/skills-lock.json` | lock file + CI check script | CI падает при drift hash без обновления lock | Средний | Script warn-only |
| CMD4.5 | HITL card UX + audit `skill_managed` | hitl + intent mutation axis если нужно | Одноразовость карточки | Средний | — |
| CMD4.6 | Eval: agent cannot persist skill without approval; malicious body rejected | tests | 100% deny без HITL | Низкий | — |

**Стоимость/latency:** редкий path; не на каждый turn.  
**DoD фазы 4:** flag default off в prod до soak; HITL обязателен; lint+scan; progressive disclosure не ломается; lockfile для product skills.

---

### Сводка приоритетов

```
CMD0 (measurability) → CMD1 (ASI-06) → CMD2 (prompt tiers + AGENTS.md)
                    ↘ CMD3 (memory tools; может частично параллельно CMD1.2+)
                         → CMD4 (skills; после CMD3 pin discipline)
```

Параллелить CMD3 с CMD1 допустимо после CMD1.1–1.2 (нужны поля origin/trust для explain).

---

## 5. Что НЕ делать (anti-patterns)

| Anti-pattern | Почему опасно | Что делать вместо |
|---|---|---|
| **Hermes file-SoT** / грузить `.agent/MEMORY.md` в product prompts | Два SoT, нет RLS/PII/audit | Structured medium + AGENTS.md только как rules |
| **Neo4j-only / Qdrant** | Ломает ADR 0004 / 060 | Promote-only L4 |
| **Unbounded medium growth** без retention | Storage Exhaustion / Silent Memory Death | Уже retention; + shorter TTL для `inferred` |
| **Self-feeding**: extract пишет verified → recall → extract усиливает ложь | ASI-06 | origin ceiling + corroboration |
| **Полная история в каждый LLM call** | Context rot, cost | JIT + compact + budgets (уже); tiers |
| **Кэш на volatile prefix** (memory snapshot в cacheable system) | Cache poisoning / stale beliefs | Только stable cache_control |
| **Новый memory tool без правки 070** | Дрейф контракта | Онбординг 070 |
| **skill_manage без HITL / без lint** | Supply-chain + prompt injection в procedural layer | CMD4 gates; default flag off |
| **Точечные phrase-lists** для extract admission | 055 | Оси task_kind/strategy |
| **Прямой MemoryPort.put из агента** | Обход audit | MCP / MemoryWriteService |
| **Интерактивный HITL на каждый sleep-time extract** | Убьёт автоматизацию dreaming | Staged trust, не card-per-fact |
| **Ослабление теста**, чтобы «прошёл» ASI-06 | 050/075 | Чинить код |
| **Смешивать DX `skills-lock.json` с product procedural lock** | Ложный security signal | Разные файлы/пути |

---

## 6. Открытые вопросы к команде

| # | Вопрос | Статус | Решение |
|---|---|---|---|
| Q1 | Filesystem vs blob для skills / AGENTS.md | **CLOSED 2026-11-03** | Runtime `AGENTS.md` + procedural `SKILL.md` = **filesystem** (git/PR). Динамическая память/state = **Postgres/Blob** (ADR 0003/0004) |
| Q2 | ADR на origin/trust ceiling? | **CLOSED 2026-11-03** | **ADR 0008 обязателен** (`docs/adr/0008-memory-origin-trust-ceiling.md`, status proposed → accepted после soak) |
| Q3 | `memory_audit` виден только owner или admin role? | **CLOSED 2026-11-03** | **Owner-scoped v1** (RLS + tool listing); admin cross-tenant audit — отдельная задача |
| Q4 | Текст `AGENTS.md`: кто SoT редактор (платформа vs EDMS embed)? | open | Платформенный короткий шаблон; embed overrides — вне scope |
| Q5 | Corroboration threshold (turns/threads)? | **CLOSED 2026-11-03** (дефолт) | peer-extract (≥2 independent `source_task_id`) **or** verified-overlap; promote_min остаётся для L4 gate |
| Q6 | Включать ли `memory_verify` в Researcher allow-list сразу? | **CLOSED 2026-11-03** | **Да** в Researcher: read `explain_belief`/`memory_audit` + `memory_verify` с pin `requires_hitl=true` (не silent write). Admin ACL — вне v1 |

---

## 7. Соответствие OWASP Agentic (срез после CMD1–3)

| ID | Тема | После плана |
|---|---|---|
| ASI-01 Prompt injection | Уже fence/scan; + AGENTS.md cap | ⚠️→✅ stronger |
| ASI-02 Tool misuse | MCP pins + RBAC | ✅ |
| ASI-03 Excessive agency | Closed 070 + HITL writes | ✅ (+ skill_manage HITL) |
| ASI-04 Supply chain MCP | Pins/fingerprint | ✅ |
| ASI-05 Unsandboxed code | Нет arbitrary code tool | ✅ |
| ASI-06 Memory poisoning | **CMD1+CMD3** | ⚠️→✅ |
| ASI-07 Inter-agent | Typed AgentOutput; no raw dump | ✅ |
| ASI-08 Cascading / breaker | resilience + kill switch | ✅ |
| ASI-09 Audit trail | mcp_tool_calls + audit log | ✅ (+ verify/skill events) |
| ASI-10 Kill switch | admin kill switch | ✅ |

---

## 8. Enforcement

| Гейт | Где |
|---|---|
| Нет Hermes/Qdrant/Neo4j-only в PR | ревью + этот план §0 |
| Новые memory tools = правка 070 | PR checklist + `tool_policy` tests |
| Origin ceiling flag documented | `docs/runbook.md` §memory (CMD1) |
| ASI-06 eval | `tests/eval/test_memory_asi06_poisoning.py` |
| Product skill lock | CI script (CMD4) |
| TODO ticket | `plans/context-memory-dialog-2026.md §N` |

---

## 9. Definition of Done (весь план)

1. Prompt assembly имеет три явных tier’а; cache только на stable.
2. `AGENTS.md` опционально в stable JIT; `.agent/MEMORY.md` никогда в runtime.
3. У каждой medium-записи есть `origin` + `trust`; extract стартует как `inferred`.
4. Promote/hot-recall уважают ceiling; poisoning eval зелёный.
5. MCP: `explain_belief`, `memory_audit`, `memory_verify` в 070 + pins + tests.
6. `skill_manage` за флагом, HITL+lint; product lock отделён от DX lock.
7. Нет предложений file-SoT / Neo4j-only / Qdrant; ADR 0003/0004 не нарушены.
8. Каждая волна имеет rollback flag или revert path.

---

## 10. История решений

| Дата | Решение |
|---|---|
| 2026-11-03 | Этап 1 инвентаризации принят; Hermes = DOC_ONLY |
| 2026-11-03 | Владелец подтвердил этапы 2–5 и фокус на PARTIAL/MISMATCH выше |
| 2026-11-03 | Self-authored skills разрешены **только** как HITL+lint (исключение из memory-max-pro §4 out-of-scope) |
| 2026-11-03 | Q1 filesystem для AGENTS/SKILL; Q2 ADR 0008 обязателен; работа на `dev` без ветки/коммитов агентом |
| 2026-11-03 | CMD2 DONE: PromptAssemblyPolicy + AGENTS.md JIT; пилот Intent/Researcher/Formatter |
| 2026-11-03 | P0/P1 soak prep: corroboration in consolidate; inferred TTL 7d; runbook §17.1; PromptAssembly on Critic/Keeper/Contextualizer; identity pins in dialog window |
| 2026-11-03 | CMD2 remainder: PromptAssembly on Analyst/Coder/TextIngestor + Researcher MCP synthesis; CMD3/CMD4 marked DONE; skills-lock warn-only in pre-commit/ci_quality |
| 2026-11-03 | P0/P1 ops: corroboration_owner_ids RPC + compose MEMORY_ORIGIN_CEILING; prompt cache token metrics; identity pin eval; Q3/Q5/Q6 closed; ADR 0008 stays proposed until staging soak |
| 2026-11-03 | Ops polish: harness records context/volatile cache-hint tiers; staging env origin/inferred/skills flags; plan §1/§2 matrices refreshed to CLOSED |

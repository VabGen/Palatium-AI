# План: Global Data Retention (2026)

Обновлено: 2026-10-05 (re-verify §11).
Источник: аудит хранилищ (PG / MinIO / Neo4j / Redis / audit / observability)
+ пробел «нет global retention cron» + сверка с корпоративными практиками 2025–2026
(GDPR storage limitation / erasure, legal hold, defensible disposition, CronJob vs
Temporal/Celery, backup «beyond use», selective purge).
Статус: **PLAN**. Норматив после волн — правила **060** (память), **020** (PII/HITL),
**040** (audit/метрики), **080** (батчи), **082** (доставка job). Этот файл — намерение
и волны (005); не второй список запретов (050).

Архитектурное основание scheduler/роли: [ADR 0002](../../docs/adr/0002-global-retention-scheduler.md).

---

## 0. Принципы (best practices 2026)

1. **Policy-as-code.** Окна и действия живут в `domain/policies/retention.py` +
   `core/config/retention.py`. Числа не размазаны по сервисам (010, 055). Категория
   данных → purpose / legal basis (документ) → TTL → disposition.
2. **Out-of-band job, не in-process cron.** Data retention ≠ HITL TTL. Job — отдельный
   процесс (CronJob / compose one-shot). APScheduler в API и Celery Beat — отвергнуты
   (ADR 0002). Temporal — backlog, если появятся multi-day compensations (см. §11).
3. **Defense in depth.** App sweeper (SoT) + object-store lifecycle (MinIO) + native Redis
   TTL. Lifecycle не заменяет политику (orphan rows / Neo4j / knowledge).
4. **RLS-совместимость.** App-роль без `BYPASSRLS` сохраняется. Global sweep — через
   узкую роль `palatium_retention` / SECURITY DEFINER, не через user JWT.
5. **Idempotent batched purge + lease.** Bounded batch, UTC-aware cutoff, advisory lock /
   job lease (K8s CronJob не даёт exactly-once). Fail одной строки не валит проход.
6. **Delete / archive / anonymize — разные действия.** Закрытый enum; soft→hard с grace;
   PII — отдельно (GDPR / 152-ФЗ). Soft-delete **не** считается erasure.
7. **Selective purge при конфликте норм.** При «надо хранить запись / надо убрать PII» —
   anonymize полей, сохранить operational shell; иначе `max(applicable windows)` +
   документированное обоснование (не молчаливый min).
8. **Audit of retention, not retention of secrets.** Каждое действие — audit event без
   payload PII (040, 020). Hash-chained audit **не** hard-delete in-place; rotate→cold.
9. **Legal hold как runtime veto.** Hold вычисляется **в момент execute**, не только при
   планировании (состояние hold могло измениться mid-batch).
10. **Lineage / derived data.** Primary → embeddings → knowledge chunks → Neo4j promote →
    MCP copies — один disposition fan-out; restore backup не воскрешает erased без
    re-apply (suppression / erasure registry).
11. **Backups in scope.** PITR/снимки — documented «beyond use» + fixed rotation; не
    «scrub prod, ignore backups».
12. **Processors in scope.** Langfuse / LiteLLM / Mem0 SaaS / embedding gateway — DPA +
    их retention windows согласованы или данные не уходят.
13. **Lazy sweep = UX-defense, не SoT.** Неактивный субъект не удерживает данные вечно.
14. **Правило без гейта — не правило.** Волна = тест + метрика + runbook + compliance
    report artifact.

---

## 1. Проблема

Нет единого оркестратора сроков хранения. Данные копятся; stale-память засоряет recall;
нет доказуемого удаления по истечении срока (GDPR Art.5(1)(e) / 152-ФЗ).

### 1.1. Инвентаризация (as-of 2026-10-05)

| Store | Пишется | Retention сейчас | Gap |
|---|---|---|---|
| `palatium_ai.sessions` | треды, context | нет | ∞ |
| `palatium_ai.dialog_turns` | транскрипт | нет | ∞ |
| `memory.entries` | medium + embedding; колонка `expires_at` | **не выставляется** при `put`; forget только HITL | мёртвое поле; 060 TTL не enforced |
| `palatium_ai.memory_items` | legacy KV | нет | уточнить: migrate или sweep |
| `knowledge.documents` / `chunks` | ingest / index | нет delete-path | ∞; не связан с attachment index TTL |
| `attachments` + MinIO | blob + derived text | per-owner lazy + `POST /sweep`; TTL 7d/365d | **нет global cron** (runbook §16.6) |
| `mcp_tool_calls` | args/content | manual CLI archive/purge | нет scheduler |
| Neo4j `MemoryFact` | promote MERGE | нет delete/TTL | forget medium ≠ graph |
| Redis (HITL, pending, cache, cost_budget, kill_switch) | ephemeral | HITL sweep + key `EX` | ок; сверить все префиксы на `EX` |
| Audit chain (файл) | append-only | нет ротации | конфликт immutability ↔ erasure |
| Structlog file handler | app logs | `maxBytes`+`backupCount=5` | возможный PII в логах → scrub/TTL |
| Loki / Prometheus | ops | 7d / 15d | ок |
| **Langfuse + ClickHouse + MinIO traces** | LLM traces (profile `observability`) | зависит от деплоя | **не было в v1 плана** — обязателен TTL/DPA |
| LiteLLM cache/logs | gateway | Redis/local | согласовать с processor retention |
| LangGraph checkpointer | short-term | MemorySaver или PG без TTL | дыра при PG mode |
| **PG backups / volume snapshots** | disaster recovery | **нет политики в репо** | **критический gap GDPR** |
| Mem0 SaaS (если `MEMORY_BACKEND=mem0`) | external medium | vendor TTL | processor + erasure fan-out |
| Attachment `contains_pii` | blob/text | общий attach/index TTL | нет укороченного PII-окна |
| Feedback | сейчас только log line | N/A | когда появится таблица — class сразу |

Фоновые задачи API: HITL sweep, memory extract. Retention-worker отсутствует.

---

## 2. Scope / вне scope

### В scope

- Доменная политика retention + конфиг окон.
- CLI/job `retention_runner` + CronJob/compose one-shot.
- Роль БД `palatium_retention` (или SECURITY DEFINER).
- Enforcement: memory `expires_at`, sessions/turns, attachments global, knowledge cascade,
  Neo4j delete/anonymize, mcp_tool_calls schedule, audit rotate-to-cold.
- Метрики, audit events, runbook, тесты.

### Вне scope (v1 кода)

- Celery / полный Temporal runtime (см. §11: CronJob достаточен сейчас; Temporal — если
  multi-day compensations / steward approval sagas станут нормой).
- Полноценный DSAR self-service UI / «download my data» portal.
- Изменение JavaEdms / EDMS document retention (чужой контур, 090/092).
- Переписывание hash-chain формата audit (только rotate + verify).
- Valkey migration (отдельный долг 001).
- Физическая NIST 800-88 media destroy для HDD (облачный clear/purge + crypto-erase
  документируется; Destroy — infra runbook, не app job).

### В scope как control-plane (не UI)

- **Erasure fan-out API/CLI** (`--user_id=…`) на том же оркестраторе, что и cron —
  корпоративный стандарт: один disposition engine для schedule и Art.17.
- Backup retention policy + restore re-apply checklist.
- Langfuse / LiteLLM retention alignment.

---

## 3. Решение: архитектура

```
domain/policies/retention.py       # RetentionClass, RetentionAction, pure rules
domain/ports/retention.py          # RetentionPlanPort / per-store adapters Protocol
core/config/retention.py           # окна из env (единственные числа)
application/services/retention/    # RetentionOrchestrator (plan → execute)
application/jobs/retention_runner.py
infrastructure/retention/          # postgres / minio / neo4j / audit adapters
deploy/cron/retention*             # K8s CronJob + compose profile
scripts/ (тонкие обёртки)          # совместимость с существующими mcp_* CLI
```

### 3.1. Scheduler

| Среда | Механизм |
|---|---|
| Prod | **Kubernetes CronJob**, `concurrencyPolicy: Forbid`, один container = one-shot runner |
| Local/staging | Compose profile `retention` / `docker compose run --rm retention` |
| CI | только **report dry-run** (не execute на prod data) |

Расписание (дефолт):

- Daily 03:40 UTC — полный оркестратор (`--all`).
- Every 6h — быстрые классы: `attachment_*`, `memory_pii` (короткое окно / объём blob).

### 3.2. Действия (закрытый перечень)

```text
RetentionAction = Literal["delete", "archive", "anonymize", "report_only"]
```

| Action | Когда |
|---|---|
| `delete` | нет регуляторной нужды хранить; blob + row + graph node |
| `archive` | soft-hide / cold table перед purge (mcp_tool_calls, sessions metadata) |
| `anonymize` | PII: tombstone текста/эмбеддинга, сохранить ключ + audit, затем grace → delete |
| `report_only` | dry-run / compliance report |

### 3.3. Матрица политик (дефолты)

| RetentionClass | Store | Action chain | Окно (default) | Env |
|---|---|---|---|---|
| `session_transcript` | sessions + dialog_turns | archive session → delete turns → purge session | **30d** inactivity | `RETENTION_SESSION_DAYS` |
| `memory_medium` | memory.entries (non-PII, non-episode) | set `expires_at` on write → delete | **30d** (060) | `RETENTION_MEMORY_MEDIUM_DAYS` |
| `memory_episode` | memory.entries `episode` | delete | **365d** | `RETENTION_MEMORY_EPISODE_DAYS` |
| `memory_pii` | memory.entries `contains_pii` | anonymize → grace → delete | **90d** | `RETENTION_MEMORY_PII_DAYS` |
| `attachment_attach` | attachments + MinIO | delete objects + row | **7d** (уже) | existing attach TTL |
| `attachment_index` | attachments + MinIO + knowledge | delete objects + row + cascade knowledge | **365d** (уже) | existing index TTL |
| `attachment_pii` | attachments `contains_pii` | anonymize derived text → delete | **min(mode_ttl, 90d)** | `RETENTION_ATTACHMENT_PII_DAYS` |
| `knowledge_orphan` | knowledge.* | delete | после cascade / без parent | `RETENTION_KNOWLEDGE_ORPHAN_DAYS` |
| `mcp_tool_call` | mcp_tool_calls | archive → soft grace → purge | **90d** / **3y** (уже CLI) | existing MCP_RETENTION_* |
| `neo4j_memory_fact` | Neo4j | anonymize/delete sync forget + PII window | PII **90d**; non-PII ceiling TBD (§8) | `RETENTION_GRAPH_PII_DAYS` |
| `audit_chain` | file → cold | rotate + verify; **no in-place delete** | hot **90d**, cold per legal | `RETENTION_AUDIT_HOT_DAYS` |
| `checkpointer` | LG checkpoints | delete by thread TTL | align session **30d** | `RETENTION_CHECKPOINT_DAYS` |
| `redis_ephemeral` | Redis | native TTL | as today | — |
| `observability_ops` | Loki/Prom | platform retention | 7d/15d | deploy configs |
| `observability_llm` | Langfuse/CH/MinIO traces | configure TTL / drop | **≤30d** default (PII-rich) | `RETENTION_LANGFUSE_DAYS` |
| `backup_snapshots` | PG/volume backups | rotate; restore+re-apply erasure | **≤35d** PITR typical / policy | ops runbook (не app table) |
| `processor_external` | Mem0 / vendor | contract erase / TTL | per DPA | feature-flag backend |

**Retention clock (явно per class):**

| Class | Clock start |
|---|---|
| sessions / turns / checkpoint | `last_activity` (не только `created_at`) |
| memory medium / episode | `created_at` (TTL на запись); optional refresh on access — **запрещён для PII** |
| memory/attachment PII | `created_at` only (access не продлевает) |
| attachments | `expires_at` (уже policy) |
| mcp_tool_calls | `created_at` → archive; `archived_at` → purge |
| graph facts | `created_at` / `updated_at`; sync forget immediate |

**PII override:** `contains_pii=true` → `min(class_window, pii_window)`; access **не** продлевает.

**Conflict rule:** overlapping obligations → selective anonymize; иначе `max(windows)` +
обоснование в policy comment / ADR amendment (не молчаливый min «чтобы быстрее удалить»).

**Legal hold:** runtime veto на execute; skip + metric `held`.

**Erasure registry:** append-only `erasure_events(user_id, at, classes)` — при restore
backup job обязан re-apply (корпоративный anti-resurrection pattern).

### 3.4. Оркестратор (один проход)

1. Acquire job lease (PG advisory lock / Redis lock); если занято — exit 0 + metric skip.
2. Load policy snapshot + holds + erasure registry.
3. Для каждого enabled class: select candidates (`LIMIT batch`, UTC cutoff).
4. Per candidate: **re-check hold** → action → audit (`retention_<action>`, ids only) →
   metrics; для hard delete — запись в erasure registry при user-scoped erase.
5. Порядок каскада (lineage): blobs → derived text → PG row → knowledge chunks →
   Neo4j → mcp archive (не наоборот: иначе orphan blobs).
6. Partial failure: log + counter; continue batch.
7. Exit non-zero только при hard failure (DB down, config invalid, lease broken).
8. `--dry-run` default; `--execute` явный; опционально `--require-approve-token` для
   irreversible classes (`mcp_tool_call` purge, mass session delete) на первых прогонах.

### 3.5. RLS / привилегии

- API продолжает `palatium_app` **NOBYPASSRLS**.
- Job использует `palatium_retention`:
  - SELECT/DELETE/UPDATE только на retention-relevant tables;
  - либо вызов `SECURITY DEFINER` функций `retention.sweep_*()`;
  - **не** credential app-роли.
- Attachments: global job supersedes «только per-owner HTTP»; lazy GET sweep остаётся.

---

## 4. Волны

Каждая волна = код + тест + метрика/audit + runbook touch + DoD. Статус обновлять здесь,
историю не переписывать (005).

### W0 — Foundation (ADR + policy + runner skeleton)

**Статус:** done (2026-10-05)

| Deliverable | Путь |
|---|---|
| ADR scheduler/role | `docs/adr/0002-global-retention-scheduler.md` |
| Config | `core/config/retention.py` + env examples |
| Domain policy | `domain/policies/retention.py` |
| CLI skeleton dry-run | `jobs/retention.py` (`python -m palatium_ai.jobs.retention`) |
| Index | `docs/README.md`, runbook §17 |

**DoD:** `poetry run python -m palatium_ai.jobs.retention --help` и dry-run → exit 0; ADR accepted.

**Gate:** unit-тесты pure policy (окна, PII override, hold skip).

### W1 — Memory TTL enforcement (P0)

**Статус:** done (2026-10-05)

- При `MemoryPort.put`: выставлять `expires_at` по class + PII. **done**
- Search/get: не возвращать expired. **done**
- `sweep_expired_for_user` (RLS). **done**
- Backfill + global delete: SECURITY DEFINER `memory.retention_*` + role
  `palatium_retention` (миграция `d4e5f6a7b8c9`). **done**
- CLI handlers `memory_medium|memory_episode|memory_pii`. **done**

**DoD:** policy TTL tests; put пишет `expires_at`; job может backfill/sweep через RPC.
Метрика `palatium_retention_actions_total` — pending W6 registry.

### W2 — Sessions + dialog_turns + checkpointer (P0)

**Статус:** done (2026-10-05)

- Критерий inactivity: `sessions.updated_at` + `RETENTION_SESSION_DAYS`. **done**
- Cascade: turns delete → session delete (`SessionTranscriptRetentionHandler`). **done**
- Index `ix_sessions_updated_at`. **done**
- Postgres checkpointer cleanup aligned 30d. **done**
  (`CheckpointerRetentionHandler`: inactive sessions + orphan LG thread keys).

**DoD:** CLI dry-run/`--execute --class session_transcript` purges inactive batch;
`--class checkpointer` no-ops when LG tables absent.

### W3 — Attachments global + MinIO lifecycle + knowledge cascade (P0)

**Статус:** done (2026-10-05) — MinIO bucket lifecycle safety-net still ops (W6)

- Global sweep всех expired (retention role), batch как сейчас. **done**
  (`AttachmentRetentionHandler` + `palatium_ai.retention_*` SECURITY DEFINER,
  миграция `e5f6a7b8c9d0`).
- При purge: cascade `knowledge.documents` (+ chunks via FK). **done**
- Orphan knowledge sweeper (`knowledge_orphan`). **done**
- MinIO bucket lifecycle = safety net (возраст ≈ max attach/index TTL). **ops/W6**

**DoD:** неактивный owner с expired attach теряет blob+row без вызова HTTP; knowledge не остаётся.
Runbook §16.6 / §17: global cron = SoT, lazy = defense.

### W4 — Neo4j + forget sync (P1)

**Статус:** pending

- `GraphWritePort.delete_fact` / `anonymize_fact` (параметризованный Cypher).
- `forget_memory` после approve: medium **и** graph.
- Retention class `neo4j_memory_fact` для PII/stale.

**DoD:** forget удаляет оба слоя; PII graph node ≤ 90d; тест на parameterized Cypher only.

### W5 — MCP tool calls schedule + audit rotate (P1)

**Статус:** pending

- CronJob вызывает существующие `archive_mcp_tool_calls` / `purge_archived_*` (dry-run default).
- Audit: rotate hot file → cold object (WORM/immutability where available) + `verify_chain`.
- Erasure request path: metadata redaction policy documented (не ломать chain mid-file).

**DoD:** daily job archives 90d+; purge 3y+; audit rotate verified in staging.

### W6 — Ops hardening + processors + backups (P1)

**Статус:** pending

- K8s manifest + compose profile (`successfulJobsHistoryLimit` / `failedJobsHistoryLimit`).
- Alerts: failures > 0; candidates growing N days; job missed schedule; lease collisions.
- Admin/CLI retention report (все classes) = **compliance certificate** (counts + windows +
  last success timestamp).
- Legal hold admin API (admin role, 020).
- Erasure CLI: `--user_id` fan-out на те же adapters.
- Langfuse/LiteLLM TTL documented + configured.
- Backup rotation policy в runbook + restore drill checklist (re-apply erasure registry).
- Annual policy review reminder (marker/ticket, не код).

**DoD:** staging CronJob green 7 days; alert rules; ops-readiness + backup §; Langfuse ≤30d.
**Gate:** restore-drill doc exists; erasure dry-run for one fixture user covers all classes.

---

## 5. Observability

Имена — только через реестр **040** (не плодить локальные):

| Metric | Labels |
|---|---|
| `palatium_retention_candidates_total` | `class` |
| `palatium_retention_actions_total` | `class`, `action` |
| `palatium_retention_held_total` | `class` |
| `palatium_retention_failures_total` | `class`, `reason` |
| `palatium_retention_duration_seconds` | `class` |

Audit events (metadata ids only): `retention_planned`, `retention_deleted`,
`retention_archived`, `retention_anonymized`, `retention_hold_skipped`,
`retention_job_started`, `retention_job_finished`.

---

## 6. Enforcement / гейты

| Gate | Где | Что роняет |
|---|---|---|
| Policy unit tests | `tests/unit/test_retention_policy.py` | неверный PII override / hold |
| Integration sweep | `tests/integration/test_retention_*.py` | expired не удаляется; живое удаляется |
| Dry-run default | CLI exit / flag parse test | execute без флага |
| No BYPASSRLS on app role | existing alembic invariant + review | retention credential reused by API |
| Docs sync | 086 | runbook/ADR/index без строки |
| Nightly dry-run report (optional) | GHA schedule | candidates explode unnoticed |

---

## 7. Отвергнутые альтернативы (кратко)

| Альтернатива | Почему нет |
|---|---|
| APScheduler в API process | multi-replica races; couples retention to API liveness; смешивает с HITL |
| Celery Beat | нет Celery в стеке; broker+workers ради cron |
| Только per-owner HTTP sweep | неактивный user = вечные данные; не GDPR |
| App role + BYPASSRLS | ломает Zero Trust RLS (060/020) |
| MinIO lifecycle alone | не чистит PG/Neo4j/knowledge/audit |
| Hard-delete audit chain | уничтожает integrity evidence (040) |

Полный разбор — ADR 0002.

---

## 8. Открытые вопросы

1. **`memory_items`:** ещё используется runtime или только legacy? → confirm → migrate/drop/sweep.
2. **Legal hold storage:** PG table `retention_holds` (рекомендация) vs Redis.
3. **Cold audit backend:** MinIO Object Lock vs внешний WORM?
4. **Graph non-PII long-term:** бессрочно + hold, или ceiling (3y) + re-consent?
5. **Steward approval gate:** нужен ли HITL/admin token на первый execute irreversible
   classes в prod, или достаточно dry-run + change window? (enterprise default: да на
   первые N прогонов / на purge > threshold).
6. **Backup product:** что реально в staging/prod (pgBackRest / volume snapshot / none)?
   Без ответа W6 backup § остаётся документационным долгом.
7. **Mem0/Graphiti prod usage:** если backend ≠ postgres — сроки DPA обязательны до GA.

Закрывать здесь со ссылкой на решение; не переписывать историю.

---

## 11. Re-verify 2026-10-05 — вердикт

### 11.1. Что уже соответствовало корпоративному уровню

| Практика (2025–2026) | В плане v1 |
|---|---|
| Category-level retention schedule + disposition | да (§3.3) |
| Policy-as-code / centralized engine | да |
| Out-of-band schedule (не in-app Beat) | да (ADR 0002); CronJob = industry default для coarse cleanup |
| Legal hold override | да |
| Anonymize vs delete vs archive | да |
| Batched idempotent purge | да |
| Audit trail of disposition | да |
| RLS-safe privileged job role | да (сильнее среднего SaaS) |
| Defense in depth (app + object lifecycle) | да |
| Soft-delete ≠ GDPR erasure (hard/anonymize) | учтено в принципах после re-verify |

### 11.2. Пробелы v1 → закрыты в этом diff

| Пробел | Корпоративный стандарт | Исправление |
|---|---|---|
| Backups / PITR вне scope | GDPR erasure «includes backups beyond use» | class `backup_snapshots` + W6 drill |
| Langfuse / LLM traces | PII-rich processor logs | class `observability_llm` |
| Lineage cascade order | derived zones (Solix/Atlan) | §3.4 шаг 5 |
| Erasure = тот же engine | Art.17 fan-out | control-plane `--user_id` + erasure registry |
| CronJob not exactly-once | lease / advisory lock | §3.4 шаг 1 |
| Conflict of norms | selective purge / max(window) | §3.3 conflict rule |
| Retention clock | event-based vs created_at | таблица clock start; PII no extend-on-access |
| Attachment PII | shorter window | class `attachment_pii` |
| Proof artifact | deletion certificate / report | W6 compliance report |
| Processors (Mem0/LiteLLM) | DPA + TTL | inventory + W6 |

### 11.3. Сознательно не берём (пока)

| Практика | Почему отложено |
|---|---|
| **Temporal Schedules** как SoT | нет Temporal в стеке; CronJob+idempotent runner покрывает coarse daily/6h jobs. Пересмотр, если появятся multi-day steward sagas / per-tenant dynamic schedules |
| **Celery Beat** | нет Celery; leader-election tax без выгоды |
| **Per-delete human steward approval forever** | Atlan-style gate полезен на старте; постоянно на каждом row — ops-killer. Компромисс: approve-token на irreversible class / threshold |
| **Table partitioning drop** | scale optimization после объёмов; не блокер compliance |
| **Full DSAR portal** | UI вне scope; CLI/API engine — в scope |

### 11.4. Итоговый вердикт

План **после re-verify** соответствует практикам крупных организаций 2025–2026 для
SaaS/AI-платформы нашего размера: centralized policy, out-of-band job, hold, lineage,
audit, backup/processor awareness, erasure fan-out. Это **не** полный GRC-продукт
уровня bank records management (SEC 17a-4 WORM на всё, Airflow/Temporal estate) — и
это правильно: YAGNI до появления требования.

Оставшиеся риски — только **открытые вопросы §8** (особенно backup product и Mem0),
не дыры в модели.

---

## 9. Порядок внедрения (рекомендуемый)

```text
W0 → W1 → W2 → W3 → W4 → W5 → W6
         ↘ parallel: mcp CLI schedule (часть W5) можно раньше как thin CronJob
```

P0 = W0–W3 (compliance + cost + search quality).  
P1 = W4–W6 (graph, audit, processors, backups, erasure CLI).

---

## 10. Definition of Done (весь план)

- [ ] ADR 0002 accepted, индекс обновлён.
- [ ] Все RetentionClass из §3.3 либо enforced, либо явно `report_only` с owner/ticket.
- [ ] Global CronJob в staging отрабатывает daily; метрики и alerts живы.
- [ ] Runbook: как запустить dry-run/execute, как hold, как диагностить failures.
- [ ] 060/runbook §16: «global cron есть»; lazy sweep — defense in depth.
- [ ] Regression suite зелёный в CI (unit+integration, без live secrets).

# Global data retention — настройки и использование

Операторский гайд по единому retention-job платформы (GDPR / 152-ФЗ storage
limitation). Архитектурное решение — [`adr/0002-global-retention-scheduler.md`](adr/0002-global-retention-scheduler.md);
волны и политика — [`.cursor/plans/global-retention.md`](../.cursor/plans/global-retention.md);
симптомы/фиксы — [`runbook.md`](runbook.md) §16.6 / §17.

## 1. Зачем и что не делать

| Делать | Не делать |
|--------|-----------|
| Out-of-band CLI / K8s CronJob | APScheduler / Celery внутри API |
| `SECURITY DEFINER` + роль `palatium_retention` | `BYPASSRLS` на app-роли API |
| Сначала dry-run, потом `--execute` | `RETENTION_EXECUTE=true` в prod без review |
| Global job = SoT для attachments | Только `POST /api/attachments/sweep` как единственный механизм |

Lazy per-owner sweep (§16.6) и MinIO lifecycle — **defense in depth**, не замена cron.

## 2. Предварительные условия

```powershell
# Миграции retention RPCs + индексы
poetry run alembic upgrade head
# Ожидаемые ревизии: d4e5f6a7b8c9 (memory) · e5f6a7b8c9d0 (attachments/knowledge/checkpoints)
```

Проверка функций (пример):

```powershell
docker compose exec postgres psql -U postgres -d postgres -c "\df memory.retention_*"
docker compose exec postgres psql -U postgres -d postgres -c "\df palatium_ai.retention_*"
docker compose exec postgres psql -U postgres -d postgres -c "\df knowledge.retention_*"
```

Env: скопируйте блок **§10b** из [`env/.env.example`](../env/.env.example) в активный
`env/.env` (или профиль). SoT чисел в коде — `RetentionConfig` /
`domain/policies/retention.py`.

## 3. Переменные окружения

### 3.1. Global job (`RETENTION_*`)

| Переменная | Default | Назначение |
|------------|---------|------------|
| `RETENTION_SESSION_DAYS` | `30` | Inactivity cutoff для `sessions.updated_at` → class `session_transcript` |
| `RETENTION_MEMORY_MEDIUM_DAYS` | `30` | TTL non-episode / non-PII medium memory |
| `RETENTION_MEMORY_EPISODE_DAYS` | `365` | TTL `memory_type=episode` (non-PII) |
| `RETENTION_MEMORY_PII_DAYS` | `90` | Потолок для `contains_pii` в memory (`min` с class window) |
| `RETENTION_ATTACHMENT_PII_DAYS` | `90` | Политика PII для attachments (class `attachment_pii`) |
| `RETENTION_KNOWLEDGE_ORPHAN_DAYS` | `7` | Grace для knowledge без parent-attachment |
| `RETENTION_GRAPH_PII_DAYS` | `90` | Neo4j MemoryFact PII (W4; пока report/policy) |
| `RETENTION_AUDIT_HOT_DAYS` | `90` | Hot audit rotate (W5; `report_only` в job) |
| `RETENTION_CHECKPOINT_DAYS` | `30` | LangGraph `public.checkpoints*` (inactive + orphans) |
| `RETENTION_LANGFUSE_DAYS` | `30` | Ops/docs TTL Langfuse (`report_only` в job) |
| `RETENTION_MCP_ARCHIVE_DAYS` | `90` | Align с MCP archive schedule (W5 wire) |
| `RETENTION_MCP_PURGE_YEARS` | `3` | Align с MCP purge |
| `RETENTION_BATCH_SIZE` | `200` | Потолок кандидатов на class за один проход (≤5000) |
| `RETENTION_ANONYMIZE_GRACE_DAYS` | `7` | Grace после anonymize перед delete (PII classes) |
| `RETENTION_EXECUTE` | `false` | Destructive без CLI `--execute`; в prod держать `false` |

### 3.2. Связанные knobs (не дублируют SoT job)

| Переменная | Роль |
|------------|------|
| `ATTACHMENTS_ATTACH_TTL_SECONDS` | Пишет `expires_at` для `mode=attach` (обычно 7d) |
| `ATTACHMENTS_INDEX_RETENTION_DAYS` | Пишет `expires_at` для `mode=index` (обычно 365d) |
| `ATTACHMENTS_PRESIGNED_TTL_SECONDS` | Stale-`pending` reclaim (тикет истёк) |
| `ATTACHMENTS_SWEEP_BATCH_SIZE` | Только per-owner lazy / `POST /sweep` |
| `MCP_RETENTION_*` | Отдельные offline-скрипты MCP tool calls ([`handbook.md`](handbook.md) §15) |
| `LANGGRAPH_CHECKPOINT_POSTGRES` | Если `false` — class `checkpointer` no-op (`tables_absent`); unset → on в staging/prod |
| `MEMORY_SESSION_TTL_SECONDS` | Hot dual-TTL для `checkpointer` (default 1800); cold = `RETENTION_CHECKPOINT_DAYS` |

## 4. RetentionClass и статус реализации

| Class | Действие job | Store | Статус |
|-------|--------------|-------|--------|
| `session_transcript` | delete turns → sessions | `palatium_ai.sessions` / `dialog_turns` | **W2 done** |
| `memory_medium` / `memory_episode` / `memory_pii` | backfill `expires_at` → delete | `memory.entries` (SECURITY DEFINER) | **W1 done** |
| `checkpointer` | delete LG rows | `public.checkpoints*` | **W2 done** |
| `attachment_attach` / `attachment_index` / `attachment_pii` | blob + row + knowledge cascade | attachments + MinIO + knowledge | **W3 done** |
| `knowledge_orphan` | delete orphan documents | `knowledge.documents` (+ chunks CASCADE) | **W3 done** |
| `mcp_tool_call` | archive/purge | `mcp_tool_calls` | scripts §15; cron wire **W5** |
| `neo4j_memory_fact` | anonymize/delete | Neo4j | **W4** |
| `audit_chain` / `observability_*` / `backup_snapshots` / … | `report_only` или ops | вне app-таблиц | **W5–W6** |
| `report_only` | noop snapshot | — | всегда |

Список имён в рантайме: `poetry run python -m palatium_ai.jobs.retention --list-classes`.

## 5. CLI

Entrypoint: `python -m palatium_ai.jobs.retention`.

| Флаг | Смысл |
|------|--------|
| (нет флагов) | Dry-run **всех** classes (policy snapshot для неподключённых) |
| `--list-classes` | Печать идентификаторов и exit 0 |
| `--class NAME` | Повторяемый фильтр (можно несколько) |
| `--batch-size N` | Override `RETENTION_BATCH_SIZE` на этот прогон |
| `--execute` | Применить dispositions (или `RETENTION_EXECUTE=true`) |

Exit codes: `0` ok · `2` config · `3` runtime.

### 5.1. Типовой прогон (local / staging)

```powershell
# 1) Миграции
poetry run alembic upgrade head

# 2) Только отчёт (безопасно)
poetry run python -m palatium_ai.jobs.retention --list-classes
poetry run python -m palatium_ai.jobs.retention
poetry run python -m palatium_ai.jobs.retention --class memory_medium --class session_transcript
poetry run python -m palatium_ai.jobs.retention --class checkpointer --class attachment_attach --class knowledge_orphan

# 3) После review dry-run — узкий execute
# poetry run python -m palatium_ai.jobs.retention --execute --class session_transcript
# poetry run python -m palatium_ai.jobs.retention --execute --class memory_medium
# poetry run python -m palatium_ai.jobs.retention --execute --class attachment_index
# poetry run python -m palatium_ai.jobs.retention --execute --class knowledge_orphan
# poetry run python -m palatium_ai.jobs.retention --execute --class checkpointer
```

Blob backend для attachment-classes берётся из `ATTACHMENTS_BLOB_BACKEND` /
MinIO (тот же factory, что у API). Job должен видеть тот же bucket, что и API.

### 5.2. Рекомендуемое расписание (пока нет K8s-манифеста W6)

| Когда | Команда | Примечание |
|-------|---------|------------|
| Daily | dry-run всех DB-classes | лог → SIEM / файл |
| Daily (после review) | `--execute` по memory + session + checkpointer + attachments + orphan | `concurrencyPolicy: Forbid` |
| Weekly | MCP scripts (`handbook` §15) | пока отдельно от оркестратора |

Compose profile / CronJob — волна W6 плана.

## 6. Как устроено (кратко)

```
CLI → RetentionOrchestrator → RetentionClassHandler
         │
         ├─ MemoryRetentionHandler      → memory.retention_*
         ├─ SessionTranscriptRetentionHandler → SQL sessions/turns
         ├─ CheckpointerRetentionHandler → public.checkpoints*
         ├─ AttachmentRetentionHandler  → palatium_ai.retention_* + BlobStore + knowledge.retention_delete_by_attachment
         └─ KnowledgeOrphanRetentionHandler → knowledge.retention_*orphans*
```

- Политика disposition: `RetentionPolicy.decide` (`delete` / `anonymize` / `archive` / `report_only`).
- PII: `effective_days = min(class, pii)`; access **не** продлевает PII-clock.
- Attachments: reclaimable = `expires_at <= now` **или** stale `pending` после
  `ATTACHMENTS_PRESIGNED_TTL_SECONDS`; cascade knowledge по `source_document_id`
  (`<uuid>` или `project:<id>:<attachment_hex>`).
- Checkpointer: ключ LG = `thread_id:task_id` ([`run_config.py`](../src/palatium_ai/application/orchestration/run_config.py));
  чистятся inactive sessions и orphan keys без строки в `sessions`.

Код:

- `src/palatium_ai/jobs/retention.py`
- `src/palatium_ai/application/services/retention/`
- `src/palatium_ai/infrastructure/retention/`
- `src/palatium_ai/core/config/retention.py`
- `src/palatium_ai/domain/policies/retention.py`
- Alembic: `d4e5f6a7b8c9_*`, `e5f6a7b8c9d0_*`

## 7. Диагностика

| Симптом | Что проверить |
|---------|----------------|
| `tables_absent` у `checkpointer` | `LANGGRAPH_CHECKPOINT_POSTGRES`; был ли `AsyncPostgresSaver.setup()` |
| `candidates=0` при ожидаемых данных | timezone `expires_at` / `updated_at`; class filter (`attachment_pii` vs attach) |
| Attachment execute `failed>0` | MinIO/credentials; тот же bucket; логи `retention.attachment_purge_failed` |
| Memory RPC permission denied | миграция применена; GRANT на `palatium_app` / current user |
| Knowledge остаётся после attach purge | `--class knowledge_orphan` после grace; `source_document_id` формат |
| Job трогает «живые» сессии | `RETENTION_SESSION_DAYS`; clock = `sessions.updated_at`, не `created_at` |

Полезные SQL — [`runbook.md`](runbook.md) §16.7 (attachments) и:

```powershell
# Inactive sessions (UTC)
docker compose exec postgres psql -U postgres -d postgres -c "SELECT thread_id, updated_at FROM palatium_ai.sessions WHERE updated_at < now() - interval '30 days' ORDER BY updated_at LIMIT 20;"

# Memory due
docker compose exec postgres psql -U postgres -d postgres -c "SELECT count(*) FROM memory.entries WHERE expires_at IS NOT NULL AND expires_at <= now();"
```

## 8. Связанные документы

| Документ | Зачем |
|----------|--------|
| [`adr/0002-global-retention-scheduler.md`](adr/0002-global-retention-scheduler.md) | Почему CronJob + retention role |
| [`.cursor/plans/global-retention.md`](../.cursor/plans/global-retention.md) | Волны W0–W6, матрица, DoD |
| [`runbook.md`](runbook.md) §16–§17 | Attachments TTL + короткий ops-блок |
| [`handbook.md`](handbook.md) §15 | MCP tool-call archive/purge scripts |
| [`ops-readiness.md`](ops-readiness.md) | Чеклист staging/prod |
| [`env/.env.example`](../env/.env.example) §10b | Канон env |

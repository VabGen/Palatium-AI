# 0002. Global retention — out-of-band CronJob + узкая DB-роль

- **Статус:** accepted
- **Дата:** 2026-10-05
- **Правило-владелец:** 060 (память/TTL), 020 (PII), 040 (audit), 082 (доставка); план — `.cursor/plans/global-retention.md`

## Контекст

Платформа пишет пользовательские и производные данные в PostgreSQL (sessions,
dialog_turns, memory.entries, knowledge.*, attachments, mcp_tool_calls), MinIO,
Neo4j (promoted MemoryFact), Redis и append-only audit chain. Часть контуров уже
имеет локальный TTL (attachments per-owner sweep, HITL Redis sweep, mcp_* manual
CLI, Loki/Prometheus), но **единого global retention job нет**.

Ограничения репозитория:

- `FORCE ROW LEVEL SECURITY` и app-роль без `BYPASSRLS` (060) — «одним SQL от API»
  чужие строки не видны.
- API уже держит in-process фоновые задачи (HITL sweep, memory extract); data
  retention с окнами дней/лет не должен делить с ними процесс и реплики.
- Требования GDPR / 152-ФЗ: storage limitation и доказуемое удаление/анонимизация
  по истечении срока; audit evidence при этом нельзя уничтожать in-place.

## Решение

1. **Scheduler:** Kubernetes CronJob (prod) и compose one-shot / profile
   `retention` (local/staging). Entrypoint —
   `python -m palatium_ai.jobs.retention` (имя модуля фиксируется планом).
   `concurrencyPolicy: Forbid`. Default — dry-run; execute — явный флаг/env.
2. **Не** APScheduler внутри API и **не** Celery Beat для retention.
3. **Привилегии:** отдельная роль `palatium_retention` (или SECURITY DEFINER
   функции, вызываемые только этой ролью). App-роль API остаётся без
   `BYPASSRLS`.
4. **SoT политики:** `domain/policies/retention.py` + окна в
   `core/config/retention.py`. Object-store lifecycle и Redis TTL — второй рубеж,
   не замена оркестратора.
5. **Действия:** закрытый набор `delete | archive | anonymize | report_only`;
   PII-окна жёстче ordinary TTL; legal hold пропускает кандидата.
6. **Audit chain:** rotate hot → cold + verify; hard-delete mid-chain запрещён.

## Рассмотренные альтернативы

- **APScheduler в процессе API** — при N репликах гонки/дубли; retention падает
  вместе с API; смешение short-lived HITL и long-lived purge. Отвергнуто.
- **Celery Beat** — в стеке нет Celery; broker+workers ради cron увеличивают
  supply-chain и ops-поверхность без выигрыша против CronJob. Отвергнуто.
- **Только per-owner HTTP sweep** (текущий attachments) — неактивный субъект
  никогда не попадёт под purge; не выполняет storage limitation. Отвергнуто как
  единственный механизм (lazy sweep остаётся defense-in-depth).
- **App-роль с BYPASSRLS «для удобства job»** — ломает Zero Trust RLS и расширяет
  blast radius компрометации API. Отвергнуто.
- **Только MinIO/S3 lifecycle** — не удаляет строки PG, knowledge, Neo4j, audit.
  Отвергнуто как SoT.

## Последствия

- Проще: один оркестратор, предсказуемое расписание, dry-run/audit/метрики,
  совместимость с RLS.
- Дороже: отдельный credential/роль БД, манифесты CronJob, каскады
  (attachment → knowledge, forget → Neo4j), политика cold storage для audit,
  backup rotation + erasure registry на restore, TTL Langfuse/processors.
- Job lease / advisory lock обязателен: CronJob не гарантирует exactly-once.
- Temporal/Celery не вводятся сейчас; пересмотр — если появятся multi-day
  steward sagas (см. план §11.3).
- Отдельные задачи — волны W0–W6 в `.cursor/plans/global-retention.md`.
- Операторский гайд (env / CLI / классы): [`../global-retention.md`](../global-retention.md).

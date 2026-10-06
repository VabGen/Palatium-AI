# 0003. Short-term memory — Postgres LangGraph checkpointer + retention TTL

- **Статус:** accepted
- **Дата:** 2026-10-06
- **Правило-владелец:** 060 (short-term); план — `.cursor/plans/memory-max-pro.md` §0.1 / Wave M1

## Контекст

Ранее short-term в 060 формулировался как «LangGraph checkpointer (Redis)».
В коде уже есть `AsyncPostgresSaver` (`LANGGRAPH_CHECKPOINT_POSTGRES`)
и retention class `checkpointer`. Владелец зафиксировал: **не** вводить Redis
checkpointer; TTL сессии — PostgresSaver + retention (согласовано с ADR 0002).

На 2026-10-06 текст **060 / 000 / 099** обновлён на Postgres + dual TTL.
Wave M1 реализовал `session_ttl_seconds`, deploy-default Postgres checkpointer
и dual-TTL purge в retention job.

Redis/Valkey в платформе — HITL / kill-switch / кэш, не graph checkpoints.

## Решение

1. Канонический short-term store = **LangGraph Postgres checkpointer**
   (`AsyncPostgresSaver` + существующий serde allowlist).
2. **Dual TTL (обязательно):**
   - hot: `MemoryConfig.session_ttl_seconds` / `MEMORY_SESSION_TTL_SECONDS`
     (default 1800) — inactivity / session bound;
   - cold: `RetentionConfig.checkpoint_days` / `RETENTION_CHECKPOINT_DAYS` —
     верхняя граница disposition.
   Retention job `checkpointer` purge’ит по политике «что сработало раньше»:
   cutoff = `now - min(session_ttl, checkpoint_days)` на `sessions.updated_at`
   (inactive > session_ttl **или** age > checkpoint_days).
3. **Default checkpointer:** `LANGGRAPH_CHECKPOINT_POSTGRES` unset →
   `AsyncPostgresSaver` в `staging`/`production`, `MemorySaver` в `development`
   (`Settings.postgres_checkpointer_enabled`). Явный `true`/`false` побеждает.
4. Исполнение — CronJob / compose one-shot (ADR 0002), **не** native Redis EXPIRE.
   Hot TTL = 1800s означает окно inactivity для политики; фактический reclaim —
   на следующем прогоне job (если job daily — задержка до суток). Не путать с
   in-process EXPIRE.
5. Dialog turns (`DialogTurnStore`) — отдельный append-only лог для extract;
   checkpointer ≠ transcript SoT.
6. Норма **060** — Postgres checkpointer + dual TTL (Wave M0).

## Рассмотренные альтернативы

- **Redis/Valkey checkpointer** — отвергнуто решением владельца.
- **Только in-process `MemorySaver`** — не переживает рестарт; неприемлемо для prod.
- **TTL только настройкой Postgres без retention job** — нет disposition/audit;
  отвергнуто в пользу policy-as-code (global-retention).

## Последствия

- Wave M1: `session_ttl_seconds` в конфиге, deploy-default Postgres,
  retention job уважает dual TTL, unit-тесты resume/expire cutoff.
- Ops: cadence retention CronJob должна быть согласована с ожидаемой
  «свежестью» hot TTL (иначе 1800s — только политика, не SLA purge).

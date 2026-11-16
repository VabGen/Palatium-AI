# 0013. Memory scope & curation (use_memory + verified fast-path promote)

- **Статус:** accepted
- **Дата:** 2026-11-12
- **Правило-владелец:** 060, 020; план W11 Memory Scope & Curation
- **Связанные:** [ADR 0004](0004-hybrid-memory-not-neo4j-only.md), [ADR 0008](0008-memory-origin-trust-ceiling.md), [ADR 0010](0010-agents-audit-w1-w6-closure.md)

## Контекст

Продуктовые якоря 2026:

- **ChatGPT:** Memory on/off (скрыть, не удалить); Temporary Unpersonalized (без recall/create); Clear Memories отдельно.
- **Claude:** Pause memory vs Reset; per-chat disable до первого сообщения.

Palatium SoT не меняется (ADR 0004): short = dialog/scratchpad; medium = `memory.entries`;
L4 = Neo4j **только** через promote. Нужны: per-turn изоляция персонализации,
HITL-gated clear, и быстрый promote для **verified** HITL-записей без Neo4j на chat hot-path
и без обхода OriginCeiling.

## Решение

1. **`use_memory: bool = True`** на classify/process/stream. При `False`:
   - durable Select (Medium + L4) запрещён (`MemoryRecallPolicy` → `use_memory_disabled`);
   - sleep-time extract не ставится в очередь (`ExtractAdmissionPolicy`);
   - dialog + scratchpad той же thread остаются;
   - Medium/Neo4j **не** удаляются (hide, not delete).
2. **`DELETE /api/memory/clear`** — HITL confirm → purge Medium (`MemoryPort.clear_namespace`)
   → enqueue `clear_user_graph` в durable `MemoryOpQueue` (Neo4j expire out-of-band).
3. **Hybrid promote:**
   - **Fast-path:** после HITL `save_memory` с `trust=verified`, если
     `max(importance, confidence) ≥ MEMORY_PROMOTE_FAST_MIN_SCORE` (default **0.85**) →
     enqueue `promote_entry` (`reason=immediate_verified`). Worker drain в API process
     (SKIP LOCKED), не `BackgroundTasks` / Celery.
   - **Slow-path:** `memory-consolidate` + `PromotionPolicy` + `OriginCeilingPolicy`
     **без изменений** для `inferred` / batch.
4. **Никогда** не enqueue fast-path из sleep-time extract (`inferred`), независимо от
   LLM confidence. Confidence ≠ L4 trigger.

## Рассмотренные альтернативы

- FastAPI `BackgroundTasks` / Celery для promote — отвергнуто (нет durable lease, новый брокер).
- Trigger L4 по raw LLM confidence на `inferred` — отвергнуто (ASI-06 / ADR 0008).
- Удаление Medium при `use_memory=False` — отвергнуто (ChatGPT Temporary semantics).

## Последствия

- Chat hot-path не ждёт Neo4j upsert; verified high-score facts доезжают через очередь.
- Clear необратим → короткий HITL TTL + audit `memory_clear_*`.

## Implementation status (2026-11-12)

- API + policies + `MemoryOpQueue` / worker + ADR amendments: **done**.
- Web: Settings `learnFromChats` → `use_memory` на process/stream; Clear Memories
  в Settings + composer `MemoryActions` (HITL confirm → chat card): **done**.
- Alembic: `o5p6q7r8s9t0` (`memory.ops`) — накатить на каждый стенд до smoke.

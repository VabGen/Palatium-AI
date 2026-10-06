# 0004. Hybrid memory SoT — Postgres medium + bi-temporal Neo4j long-term (не Neo4j-only)

- **Статус:** accepted
- **Дата:** 2026-10-06
- **Правило-владелец:** 060, 020, 070; план — `.cursor/plans/memory-max-pro.md` §0.2 / Wave M5

## Контекст

Контрпредложение «Cortex» требовало сделать **Neo4j bi-temporal KG единым SoT**
для эпизодической и семантической памяти, мигрировать `memory.entries` в граф и
считать promote «устаревшим копированием». Это конфликтует с действующим 060
(medium = `memory.entries` pgvector+FTS+RLS; long-term растёт только через promote)
и с уже принятыми решениями владельца (Postgres checkpointer, `SKIP LOCKED` extract
queue в Postgres).

При этом bi-temporal модель (valid-time vs system-time) — ценная capability для
long-term вопросов вида «что было истинно / что система знала на дату».

## Решение

1. **Medium SoT** остаётся PostgreSQL `memory.entries` (pgvector + FTS + FORCE RLS).
2. **Long-term SoT** — Neo4j; запись только через `MemoryPromotionService` /
   `GraphWritePort` (abstraction / promote), не ad-hoc из агентов.
3. Wave M5 вводит **bi-temporal поля** на графовых фактах/рёбрах
   (`valid_at` / `invalid_at`, system `created_at` / `expired_at`) и temporal
   queries через `graph_query`.
4. Optional `MEMORY_BACKEND=graphiti|mem0` не становится production default
   (`postgres`).
5. **Cognee** не implied runtime до отдельного ADR (решение владельца).
6. Автоматическое разрешение конфликтов в графе без HITL для high-risk / PII /
   irreversible semantic flips — запрещено (020); policy-gated supersede допустим
   для низкого риска.

## Рассмотренные альтернативы

- **Neo4j-only (Cortex)** — единый store для L3–L7. Отвергнуто: потеря RLS/FTS/
  retention SECURITY DEFINER / native 4096 embed path; стоимость graph write на
  каждый эпизод; ломка существующего spine и тестов; противоречие 060 без
  доказанного выигрыша eval.
- **Qdrant + Neo4j** — лишний vector DB; отвергнуто 060.
- **Graphiti как default MemoryPort** — optional adapter уже есть; dual-write /
  смена SoT без ADR запрещены.

## Последствия

- «Уровень бог» достигается усилением **long-term cortex** (bi-temporal + jobs),
  не сносом medium.
- Миграция «все rows → Episode nodes» как обязательный cutover — вне scope.
- Любой будущий Neo4j-only SoT требует **нового** ADR, superseding этого, и правки 060.

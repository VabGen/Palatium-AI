# 0008. Origin ceiling и staged trust для medium-памяти (ASI-06)

- **Статус:** proposed
- **Дата:** 2026-11-03
- **Правило-владелец:** 060, 020; план — `.cursor/plans/context-memory-dialog-2026.md` §3.3 / Wave CMD1
- **Связанные:** ADR 0003 (short-term), ADR 0004 (hybrid SoT), `.cursor/plans/memory-max-pro.md`

## Контекст

Sleep-time extract (`MemoryKeeper` → MCP `save_memory`) пишет в medium **без** interactive HITL
(документированный EXCEPTION 020). Запись проходит secret scan + PII + audit, но факт
становится равноправным с HITL-verified на hot-path recall и (при порогах) на promote в Neo4j.

Это открывает OWASP ASI-06 (Memory Poisoning): недоверенный transcript → extract →
`inferred` belief → self-feed на следующих turn'ах. Полный HITL на каждый extract убивает
автоматизацию «dreaming» (Letta sleep-time / Anthropic out-of-band curation).

SoT слоёв не меняется (ADR 0003/0004): short = Postgres checkpointer; medium =
`memory.entries`; long = Neo4j только через promote. File-SoT (`MEMORY.md`) отвергнут.

## Решение

1. Каждая medium-запись несёт закрытые оси (Literal в `domain/memory/types.py`):
   - **`origin`:** `user_hitl` | `extract` | `compact` | `system` | `legacy`
   - **`trust`:** `verified` | `inferred` | `quarantined`
2. Правила записи (без интерактивной карточки на extract):
   - HITL `save_memory` → `origin=user_hitl`, `trust=verified`
   - sleep-time extract → `origin=extract`, `trust=inferred`
   - context compact / system gated write → `origin=compact|system`, `trust=inferred` (system ops
     могут ставить `verified` только явно)
3. **Hot-path recall:** `quarantined` исключается; `inferred` демотируется относительно
   `verified` (score factor). Flag `MEMORY_ORIGIN_CEILING` (default on) — откат.
4. **Promote → L4:** `verified` по существующим порогам; `inferred` — только при
   `access_frequency ≥ promote_min` **и** non-PII; `quarantined` никогда.
5. **Corroboration (batch, не hot-path):** near-duplicate overlap с `verified` или со вторым
   независимым `extract` (`source_task_id`) → upgrade `inferred → verified` + метрика.
6. Legacy rows без полей: `origin=legacy`; `trust=verified` только при
   `explicit_write=true`, иначе `inferred`.

## Рассмотренные альтернативы

- **HITL на каждый extract-факт** — убивает sleep-time automation; отвергнуто владельцем плана.
- **Hermes `MEMORY.md` bounded file-SoT** — второй SoT без RLS; отвергнуто ADR 0004 / memory-max-pro.
- **Считать все MCP `save_memory` verified** — extract идёт через тот же tool; ASI-06 остаётся.
- **Отдельная quarantine-таблица** — дубль medium; достаточно trust enum в value (+ индекс позже).

## Последствия

- Проще: измеримый provenance; poisoning eval; promote не поднимает сырой extract в граф.
- Дороже: demotion может снизить Recall@k на «только inferred» сценариях — компенсируется
  corroboration + HITL verify (CMD3); нужен eval gate.
- Отдельные задачи: CMD1 реализация; опциональная колонка/индекс; ADR → `accepted` после
  зелёного ASI-06 eval и staging soak с `MEMORY_ORIGIN_CEILING=true`.

## Implementation status (code-complete on `dev`, 2026-11-03)

- Origin/trust persist + recall demotion + promote gate + ASI-06 eval: **done**.
- Corroboration batch: wired into `memory-consolidate` (compose profile `memory-jobs`),
  not a separate container; `--all-users` unions `promotion_owner_ids` ∪
  `corroboration_owner_ids` (migration `l2a3b4c5d6e7`).
- Inferred TTL: `RETENTION_MEMORY_INFERRED_DAYS` (default 7) + sticky `LEAST` on upsert.
- Status remains **`proposed`** until the soak checklist below is signed off on staging.

## Soak checklist (staging → accepted)

Не менять статус на `accepted` только потому что код на `dev`. Перед flip:

1. `MEMORY_ORIGIN_CEILING=true` на staging ≥ soak-окна (ориентир: 1–2 недели трафика).
2. `tests/eval/test_memory_asi06_poisoning.py` зелёный в CI / nightly.
3. Sleep consolidate: corroboration → promote → retention без роста error rate;
   метрики `palatium_memory_trust_upgrade_total` / origin-ceiling actions наблюдаемы.
4. `RETENTION_MEMORY_INFERRED_DAYS` (default 7) не режет HITL-`verified` факты;
   upsert `inferred` не продлевает `expires_at` (`LEAST`).
5. Rollback проверен: `MEMORY_ORIGIN_CEILING=false` возвращает pre-CMD1 recall/promote.
6. Runbook §17.1 актуален; `ALLOW_SELF_AUTHORED_SKILLS` остаётся `false` до отдельного soak CMD4.
7. Alembic head includes `l2a3b4c5d6e7` (`corroboration_owner_ids`) на staging DB.

Владелец: flip статуса ADR + запись в `docs/adr/README.md` после пунктов 1–7.

# A.4 — Root cause (P0-A / P0-B)

**Дата:** 2026-10-13  
**Ветка диагностики:** `diagnostics/p0-attachment-scratchpad`  
**Статус:** диагностика **закрыта**; два независимых root cause; оба нужны для Phase 5.

Доказательства: `A2a_test_output.txt`, `A2b_test_output.txt`, `A2d_test_output.txt`, `A2e_test_output.txt`.

---

## Вердикт (locked)

| ID | Симптом | Root cause | Доказательство |
|---|---|---|---|
| **P0-A** | `attachment_refs` / fence подменяется чужим файлом | polluted dialog prior UUID → rehydrate → `get_many(user_id)` без `thread_id` | A.2e H5b **FAIL ×2** (прогон 1 + прогон после type-fix wrapper); A.2a TypeError `thread_id` |
| **P0-B** | `memory_hints` / Contextualizer «путает» файлы сессий | `recall_for_thread` ищет `user_namespace` без thread scope; episode-факты текут в чужой тред | A.2d **FAIL**, стабильно (user-ns marker в T1 hits) |

**Независимость (доказана A.2e):** закрытие только P0-B не устраняет подмену fence (H5b). Закрытие только P0-A не устраняет user-ns bleed (A.2d). Связь «memory → rehydrate → wrong fence» **опровергнута** (A.2d fence clean; A.2e scratchpad→refs PASS). Один фикс на оба P0 **не пройдёт**.

---

## Стабильность A.2e

Воспроизводимо: **H5a PASS · H6 PASS · H5b FAIL · scratchpad→refs PASS**.

| Прогон | Итог |
|---|---|
| A.2e #1 (диагностика) | 1 failed (H5b), 2 passed |
| A.2e #2 (после type-fix `_capture_run_graph`) | 1 failed (H5b), 2 passed — тот же assert, без регрессии wrapper |

Разрыв **A.2b PASS** vs **A.2e H5b FAIL** — не противоречие: A.2b = чистый dialog; A.2e H5b = polluted prior. Подтверждение вектора, не баг теста.

Дальнейшая диагностика (источник pollution в prod) **не открывается** до merge P0-A.

---

## P0-A — attachment fence substitution

### Вектор

```
dialog.payload.attachment_ids  (чужой UUID в prior user-turn)
        ↓
AttachmentStickinessPolicy.attachment_ids_for_prior
        ↓
rehydrate(ids) → AttachmentService.build_turn_context
        ↓
get_many(ids, user_id=…)   ← НЕТ thread_id  (A.2a)
        ↓
state.untrusted_context = чужой файл
        ↓
citation_refs_from_untrusted_context → attachment_refs
```

### Усилитель

`PostgresAttachmentRepository.get_many` фильтрует только `user_id` + id  
(`attachment_repository.py`; unit A.2a: `TypeError: unexpected keyword argument 'thread_id'`).

Любой UUID того же пользователя из другого треда резолвится и попадает в fence.

### Доказательства

| Шаг | Результат |
|---|---|
| A.2b clean seed | PASS — граф не тянет A2 сам |
| A.2e H5a write | PASS — нормальная запись dialog не кросс-контаминирует |
| A.2e H6 pending | PASS — pending не селектор fence |
| A.2e H5b polluted prior | **FAIL ×2** — payload=[A2] на T1 → fence=`contract.pdf`, refs=`['contract.pdf']` |
| A.2e scratchpad→refs | PASS — refs только из fence; «refs из scratchpad» опровергнуто окончательно |

### Prod

Turn 2/3/4: `attachment_refs` = `contract.pdf` / `Заявки.pdf` / `Обращение.docx` при upload только одного файла в треде — класс H5b (fence SoT загрязнён), не «галлюцинация текста при чистом fence».

### Остаточная неопределённость (не блокер)

Источник pollution dialog prior в prod **не локализован** (H5a clean, H5b path live). Кандидаты: клиентские ids, citations в assistant payload, thread re-entry.  
**Решение:** фикс P0-A (`thread_id` в `get_many` + проброс из rehydrate) блокирует **усилитель** — достаточно для Phase 5. Если подмена повторится после PR — тикет `P0-A.2: dialog pollution source`, не блокер.

### Fix scope (PR `fix/p0-attachment-thread-isolation`)

1. `get_many(..., *, thread_id)` + SQL `AND thread_id = …`
2. Rehydrate / `build_turn_context` пробрасывает `thread_id`
3. Зелёный `test_p0_get_many_thread_isolation.py` без правки теста  
Не входит: dialog write, Contextualizer, memory/scratchpad.

---

## P0-B — user-namespace recall bleed

### Вектор

```
_recall_namespaces(thread) = [thread_ns, user_ns, ?org_ns]
        ↓
memory_port.search(user_namespace(user_id), query=…)
        ↓
durable hits source='medium' (episode/file facts из других сессий)
        ↓
memory_hints / Contextualizer reasoning («letter or contract»)
```

Scratchpad thread-scoped — **чист** (A.2d). Score=10000 — pin scratchpad (`scratchpad.py`), не root P0-B.

### Доказательство

A.2d: `P0D_USER_NS_FOREIGN_ATTACHMENT` + `unrelated.pdf` + a2 uuid в T1 `memory_hits`; fence остаётся A1. Стабильно.

### Связь с P0-A

**Опровергнута.** A.2e: scratchpad/user-text с чужим UUID не собирает `attachment_refs` — они только из fence.

### Fix scope

`B4_fix_proposal.md` (kind-gate: user-ns hot-path только `preference`) → PR `fix/p0-recall-thread-scope`.

---

## Матрица «один фикс vs два PR»

| Закрыть только | Fence wrong-file | memory_hints bleed |
|---|---|---|
| P0-B (recall) | остаётся (H5b) | уходит |
| P0-A (`get_many` thread) | уходит (усилитель) | остаётся (A.2d) |
| оба | уходит | уходит |

→ **два PR** для Phase 5.

---

## Что опровергнуто (канон)

| Гипотеза | Вердикт |
|---|---|
| Межтредовая утечка через graph/state (A.2b) | опровергнута |
| memory → rehydrate → чужой fence (старая H4) | опровергнута |
| pending_attachment_ids выбирает fence (H6) | опровергнута |
| dialog write сам кросс-пишет UUID (H5a) | опровергнута |
| `attachment_refs` собирается из scratchpad помимо fence | опровергнута окончательно (A.2e ×2) |
| `get_many` без thread — единственный SoT выбора ids | нет: ids из dialog; `get_many` — усилитель резолва |
| Один фикс закрывает P0-A и P0-B | опровергнуто |

---

## Следующие шаги (диагностика закрыта)

1. ~~A.4~~ — locked (этот файл)  
2. ~~B.4~~ — `B4_fix_proposal.md`  
3. **PR P0-A** `fix/p0-attachment-thread-isolation` (блокер Phase 5)  
4. **PR P0-B** `fix/p0-recall-thread-scope` (параллельно)  
5. C.2 smoke после обоих  
6. Пометка в `evolution-to-big-tech` — после merge

# A.1 — Attachment → context dataflow (read-only)

**Дата:** 2026-10-13  
**Ветка:** `diagnostics/p0-attachment-scratchpad`  
**Метод:** grep + чтение кода; `src/` не менялся.

## Коррекция терминов

В `AgentGraphState` **нет** поля `attachment_refs`.

| Имя | Где живёт | Роль |
|---|---|---|
| `untrusted_context: str` | `state` (`orchestration/state.py:57`) | SoT: fenced текст вложений на turn |
| `attachment_refs` | audit / formatter / extract meta | **производное** от fence через `citation_refs_from_untrusted_context` |
| `pending_attachment_ids` | `session.context` | sticky UUID-список для SB2 rehydrate |
| `TurnAttachmentContext` | ContextVar на turn | **не каталог файлов** — callbacks `rehydrate` / `clear_pending` |

Лог `agent.turn.reasoning` пишет `fields["attachment_refs"]` из финального `untrusted_context`  
(`turn_reasoning_audit.py:40-41`). Assert в тестах P0 должен смотреть на fence / derived refs, не на несуществующий `state['attachment_refs']`.

---

## Схема

```
[upload API]  →  AttachmentRepository.save(thread_id, user_id, filename, …)
                      │
                      ▼
[client turn]  →  IntentService.process / process_stream(attachment_ids=?)
                      │
                      ├─ _resolve_turn_attachment_ids  (StickinessPolicy.decide_entry)
                      │     explicit_ids  → restore_ids = explicit
                      │     pending only  → restore_ids = ()   # НЕ auto-fence (SB1)
                      │
                      ├─ session.context["pending_attachment_ids"]  ← patch если explicit
                      ├─ dialog_turn.payload["attachment_ids"]      ← только если resolved
                      │
                      ├─ _turn_untrusted_context(resolved_ids)
                      │     → AttachmentService.build_turn_context(ids, user_id)
                      │     → fenced <<<UNTRUSTED… source=attachment:<uuid>:<filename>>>
                      │
                      ▼
[IntentGraphRunner._prepare_graph_input]
                      │  graph_input["untrusted_context"] = fenced   # ПЕРВАЯ запись в state
                      ▼
[continuation_node]  StickinessPolicy.decide_rehydrate
                      │  format|answer+refers + trust_prior → ids из dialog prior
                      │  иначе clear_pending
                      │  rehydrate → может ПЕРЕЗАПИСАТЬ state.untrusted_context
                      ▼
[selectors._with_untrusted_context]  → ContextPacket.untrusted_context (budget)
                      ▼
[workers / formatter]  citation_refs_from_untrusted_context → UI chips / audit attachment_refs
```

`TurnAttachmentContext` стоит **сбоку** (ContextVar): узлы зовут `rehydrate(ids)` /
`clear_pending()`, сами UUID не выбирают.

---

## Ответы на вопросы

### 1. Кто присваивает «attachment_refs» / fence в state?

Прямые записи в **`state["untrusted_context"]`** (единственный SoT):

| # | Место | Когда |
|---|---|---|
| W1 | `intent_graph_runner.py:456` | entry graph_input |
| W2 | `nodes.py:229` (после rehydrate `nodes.py:203`) | continuation_node |

Производные **`attachment_refs`** (не state):

| Место | Что делает |
|---|---|
| `turn_reasoning_audit.py:41` | audit field из fence |
| `formatter/parsing.py:62-74` | merge в `DocumentMeta.source_refs` |
| `memory_extract.py:289` | текстовая мета в extract body |
| `attachment_stickiness.py:109` | reason string `no_dialog_attachment_refs` (не запись) |

### 2. Входы: `thread_id`, `turn_id`, `pending_attachment_ids`, stickiness?

| Вход | Роль в выборе |
|---|---|
| `thread_id` | session pending + dialog window + access check; **не** фильтр в `build_turn_context` (параметр принят, в теле не используется — `attachment_service.py:712`, `726`) |
| `task_id` (= turn) | лог/checkpoint; не селектор файла |
| explicit `attachment_ids` | API turn; побеждает в `decide_entry` (`attachment_stickiness.py:60-66`) |
| `pending_attachment_ids` | session sticky; entry **не** fenced (`skip_sticky_restore`, `:67-72`); mid-graph rehydrate / clear |
| Stickiness | entry: explicit vs skip; rehydrate: dialog-bound UUID по prior |

Lookup fence: `get_many(ids, user_id=…)` — **user_id + id**, без `thread_id`  
(`attachment_repository.py:233-244`).

### 3. «Последний загруженный из треда» vs «текущий turn»?

| Путь | Правило |
|---|---|
| Entry fence | только **explicit** ids текущего запроса |
| Без explicit | fence пустой; pending остаётся для SB2 |
| Mid-graph rehydrate | UUID из **dialog**: user-turn перед prior assistant (`attachment_ids_for_prior`, `:117-132`) |
| `list_for_thread` (newest first) | compliance/API (`:246-255`); **не** turn fence |

Итог: turn-path **не** «последний upload из БД треда». Follow-up без upload опирается на dialog payload / pending + rehydrate.

### 4. Несколько attachment в треде — что решает?

1. **Explicit multi-upload:** все ids в порядке запроса → все блоки в fence (`build_turn_context` loop `:729-733`).
2. **Rehydrate:** `_user_attachment_ids_before` идёт назад по dialog; **первый** user-turn с payload `attachment_ids` → **весь** tuple того turn (`attachment_stickiness.py:141-148`). Не «один newest по `created_at`».
3. **Нет match / new_topic:** `clear_pending` или пустой rehydrate → fence пустой.
4. **Citations:** один chip на fence; same-name → `filename#id8` (`citations.py:44-79`).

---

## Grep: `attachment_refs` в `src/` (py)

```
src/palatium_ai/application/services/turn_reasoning_audit.py:41
src/palatium_ai/application/agents/formatter/parsing.py:62
src/palatium_ai/application/agents/formatter/parsing.py:74
src/palatium_ai/application/services/memory_extract.py:289
src/palatium_ai/domain/policies/attachment_stickiness.py:109
```

Записей вида `state["attachment_refs"] = …` **нет**.

Grep записей `untrusted_context` в state/graph:

```
intent_graph_runner.py:456          # W1 entry
nodes.py:203 / :229                 # W2 rehydrate update
intent_service.py:291,490,510,688   # передача в runner (ещё не state)
```

---

## Роли файлов из ТЗ (факт vs ожидание)

| Файл | Факт |
|---|---|
| `turn_attachment_context.py` | ContextVar callbacks; не selection |
| `attachment_service.py` | fence по переданным UUID; без thread filter |
| `attachment_stickiness.py` | entry + rehydrate policy |
| `selectors.py` | читает/budget `untrusted_context`; ids не выбирает |
| `nodes.py` | единственная mid-graph перезапись fence |
| rules `*.mdc` | карта вложений в 099; метрика sticky в 040; SoT выбора — код политики |

---

## Гипотезы для A.4 (ещё без вердикта)

| # | Совместимость с A.1 |
|---|---|
| H1 sticky «последний треда» без upload | Entry **не** auto-restore; возможна путаница с **rehydrate** из dialog/pending |
| H2 selectors без `thread_id` | selectors не выбирают; но `get_many` тоже без thread_id |
| H3 nodes перезаписывает после Continuity | **Да, by design** (`nodes.py:200-229`) |
| H4 «первый по created_at» | Репо `get_many` сортирует asc, но порядок блоков = порядок **ids**; выбор ids — dialog walk, не created_at |

Следующий шаг: **A.2** — падающий тест на derived refs / `untrusted_context` (не на мифический `state['attachment_refs']`).

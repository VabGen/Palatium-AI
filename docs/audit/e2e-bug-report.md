# E2E-аудит памяти Palatium-AI (M3/M5) и живой UI-прогон

**Дата:** 2026-10-21
**Роль:** Lead QA & Architect
**Среда:** `http://127.0.0.1:5174/standalone.html`, Playwright (headless Chromium), FastAPI, PostgreSQL + pgvector, Neo4j, Redis/Valkey.
**Канонические отчёты аудита:** [`m5-verification.md`](m5-verification.md), [`m3-verification.md`](m3-verification.md).
**Дизайн M9:** [`docs/plans/m9-eval-design.md`](../plans/m9-eval-design.md). Флаги M8 в этом прогоне **не включались**.
**Артефакты прогона:** `C:\Users\Vabishchevich_H\AppData\Local\Temp\palatium-e2e\` (`s1`–`s8`, JSON-отчёты, скриншоты).

---

## 1. Итог

| Класс | Кол-во | Комментарий |
|---|---:|---|
| P0 | 1 | дубликаты активных `:MemoryFact` (M5-F6) |
| P1 | 2 | устаревший L4 после перезаписи (M5-F5 → R1.3); NL-мутации памяти отвечают «готово», ничего не записав (E2E-01/03 → R2.1). Оба закрыты |
| P2 | 4 | F5 в standalone; экранирование JSON в коде; 404 статики; HITL на read-only ответ |
| Снято повторной проверкой | 1 | `E2E-02` (P0 в первой редакции) — см. §4.2: forget **работает**, дефект был в прогоне, где клик «Забыть» не выполнялся |
| Уже исправлено в M5/M3 | 13 | F1, F1b, F2, F4, E1–E7, E2E-01, E2E-03 (см. §5) |

Главный вывод: **базовая архитектура M0–M8 выдерживает проверку** — medium остаётся PostgreSQL, long-term только Neo4j через promote, extract и promote разведены, HITL на записи работает. Найденные P0/P1 — не повод менять SoT; это дефекты идемпотентности promote, инвалидации `promoted_at` и отсутствующей интерактивной мутации памяти (не «поломка маршрутизации»).

---

## 2. Что проверялось

### 2.1. Фаза A — M5 bi-temporal cortex

Сверка с Mem0/Graphiti по ADD/UPDATE/DELETE, supersede и временным меткам:

- `MemoryFact` хранит `valid_at`, `invalid_at`, `expired_at`, `version`, `node_id`.
- `GraphFactPolicy.decide_write` различает `create` / `refresh` / `supersede` / `blocked_pii`.
- `graph_query` обязан получить `$as_of`; `assert_fact_read_is_temporal` требует полный предикат на **каждом** alias `:MemoryFact`.
- `forget_memory` делает soft-expire в графе, а не удаление узлов.

Результат: F1/F1b/F2/F4 закрыты, F3 остаётся продуктовым решением (нет `org_id` в promote). Детали — [`m5-verification.md`](m5-verification.md).

### 2.2. Фаза B — M3 durable extract

Сверка с Mem0/Letta по извлечению и sleep-time консолидации:

- `memory.extract_jobs` + `FOR UPDATE SKIP LOCKED`, lease, heartbeat, DLQ.
- `enqueue` атомарен (advisory lock + `ON CONFLICT`), есть global и per-tenant потолки.
- `_maybe_promote` отсутствует на extract-пути: `MemoryExtractService` не зависит от `MemoryPromotionService` / `GraphWritePort`.

Результат: E1–E7 закрыты, decouple подтверждён структурно. Остаточное окно fencing-token — M9-candidate, не дефект текущей волны. Детали — [`m3-verification.md`](m3-verification.md).

### 2.3. Фаза C — M9 eval design

Инвентаризация флагов M8 и условия их включения — в [`docs/plans/m9-eval-design.md`](../plans/m9-eval-design.md). Кратко:

| Флаг | Состояние | Гипотеза | Метрика включения | Откат |
|---|---|---|---|---|
| `MEMORY_IMPORTANCE_HALF_LIFE_DAYS` | активен (`7.0`) | recency-decay повышает свежесть выдачи | Recall@k + p95 | вернуть значение, не флаг |
| `MEMORY_EMBEDDING_RERANK` | `false` | rerank улучшает порядок без роста p95 | Recall@k ↑, p95 ≤ +10% | `false` |
| `MEMORY_CROSS_ENCODER_RERANK` | `false` | реальный cross-encoder лучше lexical stub | nDCG/Recall@k ↑ | `false` |
| `MEMORY_BAYESIAN_TRUST` | `false` | α/β抑制 ложные promote | blocked/supersede correctness | `false` |
| `MEMORY_BINARY_QUANTIZE_RERANK` | ручка удалена | нет `bit(4096)`-пути | — | не возвращать |
| `MEMORY_HEBBIAN_EDGE_BUMP` | ручка удалена | Select не читает вес | — | не возвращать |
| `MEMORY_XMEMORY_DECOUPLE` | `true` по гейту §5.5 | дедуп до агрегации | duplicate rate 0.25 → 0.0 | `false` |

**Ни один флаг не включается этим отчётом.** Включение — только отдельный PR с baseline «до/после» и записью в `tests/eval/test_m9_flag_gates.py`.

### 2.4. Фаза D — живой E2E UI

Сценарии: стриминг/Markdown, L1/L2-контекст, L3/L4 save + HITL, F5, supersede, forget, изоляция, edge-cases ввода. Все проверки — через реальные HTTP/SSE-запросы, без моков API.

---

## 3. Таблица дефектов

Приоритеты: **P0** — блокирует доверие к памяти/данным; **P1** — нарушает пользовательский сценарий или оставляет устаревшие данные; **P2** — UX/косметика/наблюдаемость.

| ID | Приоритет | Шаги | Ожидаемое | Фактическое | Слой |
|---|---|---|---|---|---|
| **M5-F6** | **P0** | Два promote-процесса одновременно обрабатывают один `entry_key` (плановый job + ручной `memory_promote`) | Один активный `:MemoryFact`; конкурентный promote идемпотентен | Две ноды с одинаковым `node_id`, `entry_key`, `version=1`, обе `invalid_at=NULL`, `expired_at=9999`, созданы с разницей 5 мс | M5 / `Neo4jGraphWritePort` |
| **M5-F5** | **P1** | Medium-строка уже promoted; сохранить новое значение (5433 → 5434); запустить promote | Кандидат снова виден; L4 получает version 2, старый факт superseded | `promoted_at` остаётся, `list_promotion_candidates` строку не видит, L4 навсегда хранит 5433 | M5 / `PostgresMemoryPort.put` |
| **E2E-01** | **P1** | В чат: «Забудь про порт базы данных» / «Запомни, порт 5433» | HITL-карточка соответствующей мутации либо явный отказ «не умею» | Ответ «Порт 5433 успешно настроен…» / «Принято. Запомнил», HITL нет; в новом треде значения нет. В том же треде ответ опирается на L1, что маскирует отсутствие записи | M1/M2 + capability gap |
| **E2E-03** | **P1** | NL save 5432 → NL save 5433 → новый диалог → «На каком порту база?» | 5433 | Карточка выбора из 6 портов (3306/5432/1433/27017/6379/1521), 5433 не назван | то же, что E2E-01 (не M4 recall) |
| **M5-F3** | **P1** | PII-факт меняет текст; promote | HITL-карточка на supersede либо явный отказ с каналом | `blocked_pii`, счётчик/алерт есть, но применить изменение нечем: `PromotionCandidate` не несёт `org_id` | M5 + 020 HITL |
| **E2E-04** | **P2** | Отправить сообщение → F5 в standalone | Тред и транскрипт сохранены | `sessionStorage` меняется на новый `thread-…`, сообщений 0; в host-режиме (`?preload`/`#btn-context`) сохраняется | web / bootstrap |
| **E2E-05** | **P2** | Попросить Python-код с JSON | В коде `{"name": "Alice"}` | В DOM `'{&amp;quot;name&amp;quot;…}'` — двойное экранирование кавычек | web / Markdown code |
| **E2E-06** | **P2** | Открыть страницу | Нет ошибок в console | `Failed to load resource: 404` на каждом load | web / static |
| **E2E-07** | **P2** | Новый диалог → «На каком порту QA-база?» (после явного save) | Читательский ответ 5433 | 5433 + HITL «Yes, 5433 is correct / No» (write-style карточка на read-only) | M4/M5 + CriticPolicy |

### 3.1. Что прошло без дефектов

| Проверка | Факт |
|---|---|
| Стриминг | Первый видимый текст ~222 мс, рост длины 18 → 679 символов; `streaming=true` в процессе |
| Markdown-таблица | 1 таблица, 4 строки/12 ячеек, ширина 724 px внутри bubble 756 px, горизонтального overflow нет |
| Код | 8 `pre/code`, `data-language="python"`; дефект только в экранировании кавычек (E2E-05) |
| L1/L2 | «Меня зовут Алекс…» → «Вас зовут Алекс, вы работаете над Palatium» в том же треде |
| Save + HITL | `save_memory` создаёт карточку `write`, Approve → «Запись сохранена», запись видна в новом треде |
| F5 в host-режиме | Тред `thread-5aa9…` и обе реплики восстановлены после reload |
| Supersede (явный ключ) | 5432 → 5433, новый тред отвечает 5433; оба порта одновременно не выдаются |
| Forget (панель) | Карточка `forget_memory` → Approve → «Запись удалена из памяти» |
| Изоляция | Вопрос про Python/Java не содержит портов; утечки 5433 в текст ответа нет |
| Пустой ввод | Send disabled для пустой строки, пробелов и перевода строки |
| Длинный ввод | 33 000 / 32 000 символов: Send disabled + toast; 1 200 символов — отправка работает |
| 32 000 ровно | Send остаётся доступен, счётчик «приближается к лимиту» |

---

## 4. Детали P0/P1

### 4.1. M5-F6 — дубликаты активных фактов при конкурентном promote (P0)

Фактическая проверка на живом Neo4j:

```text
node_id = 26d42a70d58bef4dbbf009e2
entry_key = qa_port_1792572741690
version = 1
text = "QA database port is now 5433"
invalid_at = NULL
expired_at = 9999-12-31T23:59:59Z
created_at = 2026-10-21T08:55:51.023Z
--- вторая нода ---
node_id = 26d42a70d58bef4dbbf009e2
... те же поля ...
created_at = 2026-10-21T08:55:51.028Z
```

Почему это P0: `:MemoryFact` с одним `node_id` и одним `entry_key` должен быть единственным активным. Дубликат означает, что recall может вернуть два противоречащих/одинаковых факта, а последующий `SUPERSEDE` обновит только одну ноду. Причина — не «редкий сбой»: `_CREATE_CYPHER` делает `CREATE`, а не `MERGE`; уникального constraint на `node_id` нет; `run_batch` не claim'ит кандидата атомарно, поэтому плановый и ручной promote могут одновременно пройти `_FIND_ACTIVE` и создать version 1.

**Фикс (M5, без смены SoT):**

1. Neo4j constraint: `CREATE CONSTRAINT memory_fact_node_id IF NOT EXISTS FOR (f:MemoryFact) REQUIRE f.node_id IS UNIQUE`.
2. `_CREATE_CYPHER` / `_SUPERSEDE_CYPHER`: `MERGE (f:MemoryFact {node_id: $node_id})` + `ON CREATE SET` / `ON MATCH SET`; `SUPERSEDE` — только после успешного claim.
3. Promote: атомарный claim кандидата (`promoted_at`/`promote_claimed_at` или `SELECT … FOR UPDATE SKIP LOCKED`) до graph write; при ошибке — release, не «тихий повтор».
4. Backfill/cleanup существующих дублей — отдельный maintenance job с audit, не ad-hoc Cypher из агента.

### 4.2. E2E-02 — снят: forget работает (исправление первой редакции)

**Первая редакция отчёта объявляла это P0 («забыли, а система всё ещё знает 5433»). Проверка показала, что дефекта нет.**

Что произошло: в прогоне `s3` (полный сценарий) панель памяти была свёрнута, кнопка режима «Забыть» не отрисовалась, Playwright упал по таймауту на клике (`forget-db-port: ok=false, TimeoutError`). Forget **не выполнялся**, поэтому следующий вопрос и вернул `5433` — память была на месте, и это корректно.

Отдельный прогон `s3_forget` с раскрытой панелью выполнил forget до конца:

```text
Панель «Забыть» → Approve → «Запись удалена из памяти»
select count(*) from memory.entries where user_id='11111111-…' and entry_key='db_port'
→ 0
Новый диалог → «Напомни порт базы данных»
→ карточка выбора типа БД (PostgreSQL / MySQL / MongoDB / …), 5433 в тексте нет
```

Вывод: forget по явному ключу инвалидирует medium-строку и не утекает в новый тред. Гипотеза «5433 приходит из L1/другого алиаса» не подтвердилась. Остаётся P2-наблюдение: после forget вопрос про порт приводит к лишней clarification-карточке вместо короткого «не знаю» (см. E2E-07, тот же слой CriticPolicy).

Что **не** покрывалось этим выводом и закрыто отдельно (R2.4): forget в **том же** треде, где значение уже лежит в L1-контексте. Сценарий «сохранили → забыли → спросили в том же треде» не проверялся; закреплённая заметка в thread-scratchpad продолжала инжектиться в recall уже после удаления из medium/L4. Фикс — fan-out forget на scratchpad (см. §6, R2.4).

### 4.3. M5-F5 — `promoted_at` не сбрасывается при изменении medium (P1)

`PostgresMemoryPort.put` в `ON CONFLICT` обновляет `value`, `search_text`, `importance`, embedding, PII/expiry, но **не трогает `promoted_at`**. `list_promotion_candidates` фильтрует `promoted_at IS NULL`. Следствие: после первого promote любое изменение текста в medium больше никогда не доедет до L4; граф навсегда хранит старую версию.

Живая проверка: строка `qa_port_1792572741690` promoted в 08:55; текст изменён на 5434; `promoted_at` остался; Neo4j active fact — 5433.

**Фикс (реализован):** сброс идёт по **содержимому факта**, а не по всему `value` — сравнение целого JSONB сбрасывало бы маркер на служебных полях (`source_task_id`, `confidence`) и заставляло повторный extract заново писать граф.

```python
content_changed = or_(
    _jsonb_text(excluded.value).is_distinct_from(_jsonb_text(MemoryEntryORM.value)),
    excluded.memory_type.is_distinct_from(MemoryEntryORM.memory_type),
)
# ...
"promoted_at": case((content_changed, None), else_=MemoryEntryORM.promoted_at),
"promote_claimed_at": case((content_changed, None), else_=MemoryEntryORM.promote_claimed_at),
```

Заявка снимается вместе с маркером: иначе протухшая claim'а заблокировала бы повторный promote на весь lease.

Regression: `tests/integration/test_memory_promotion_claim.py` — перезапись текста очищает маркер и возвращает строку в кандидаты; перезапись **того же** текста с другим `task_id`/`confidence` маркер сохраняет. In-memory паритет — `tests/unit/test_memory_promotion.py`.

### 4.4. E2E-01 / E2E-03 — NL-мутации памяти: ложное «готово» (P1)

**Уточнённая причина (первая редакция называла это «маршрутизацией намерения»): интерактивная мутация памяти в чате отсутствует как контракт.**

- `save_memory` есть только у `memory_keeper` (`application/agents/memory_keeper/config.py`), `forget_memory` — ни у одного интерактивного агента; в графе нет узла, который превращает просьбу «запомни/забудь» в HITL-карточку.
- Поэтому модель отвечает словами о выполненном действии, а `MCPToolResult` не существует. Это нарушение 030.8 (нельзя отчитываться об успехе без результата инструмента) и 060 (мутация — только через MCP).
- E2E-03 — следствие того же: `nl save` ничего не записал, новый тред честно не нашёл факт и задал уточняющий вопрос. Дефекта ранжирования recall здесь нет (в прогоне с явным `entry_key` новый тред отвечает 5433).

Проверка: `s7` (`nl-save` → «Принято. Запомнил», HITL нет) → тот же тред отвечает 5432 из L1 → новый тред значения не знает. `s3_forget` (`nl-supersede`/`nl-forget` → «успешно» без карточки) — та же картина.

**Фикс (реализован 2026-10-21, волна R2.1):**

1. Ось намерений: `MemoryMutationKind = Literal["none", "save", "forget"]` в `domain/policies/types.py`; поля `memory_mutation` / `memory_text` / `memory_key` в `IntentClassifierOutput`. Метка без payload не actionable — `parsing.py` понижает её до `none` (код > проза модели).
2. При `memory_mutation != "none"` Intent принудительно даёт `task_kind="tool_execution"`, `requires_mcp=True`, `requires_user_choice=False`, `underspecification_kind="none"` — мутация это исполнение, а не меню.
3. Граф: `route_after_intent` сразу после `NODE_INTENT_CLASSIFIER` уводит такой ход в `NODE_MEMORY_MUTATION` (`memory_mutation_node`) и в `END` — continuation, supervisor, workers и formatter не запускаются, поэтому текстовое «сохранено/удалено» физически некому произнести.
4. `MemoryMutationGate` (`application/services/memory_mutation.py`) — детерминированный, без LLM: read-check через `MemoryPort.search` → выбор существующей записи через `MemoryMutationPolicy.best_existing_match` (overlap coefficient) → `MemorySaveService.request_save` / `MemoryForgetService.request_forget` (единый путь мутации, 060). Агентless-узел, запись выполняется только после Approve через `HitlRespondFacade`.
5. Честные исходы вместо ложного успеха: нет совпадения при forget → «ничего не нашлось» без карточки; битый payload → `failure`; нет владельца/сбой staging → `failure` без записи.
6. Карточка не кэшируется: `ResponseCacheService.put_if_cacheable` пропускает ответы с `hitl_cards`, поэтому повтор хода не отдаёт мёртвую карточку.
7. `finalize_formatted_state` не перетирает уже выпущенные карточки синтетическими опциями.
8. **Recall одобренного факта (E2E-03).** Явная запись помечается `explicit_write: true` (`MEMORY_EXPLICIT_WRITE_KEY`); hot-path Select включает user-ns `fact` в hits только с этой меткой. Без неё факт, выведенный extract'ом, остаётся thread-scoped — защита P0-B от межтредового протекания не ослаблена.
9. **Fan-out на tier-кэш.** Approve записи снимает устаревшие пины `SessionScratchpad` про тот же субъект (`supersede_matching`), Approve удаления — все пины про удалённый (`forget_matching`); иначе пин со score 10 000 продолжал бы перебивать medium/L4 в том же треде (R2.4).

Regression: `tests/unit/test_memory_mutation_policy.py`, `test_memory_mutation_routing.py`, `test_memory_mutation_gate.py`, `test_response_cache.py` + сквозной `tests/integration/test_memory_mutation_turn.py` (карточка без записи до Approve; после Approve значение видно; forget удаляет только после Approve; reject не пишет ничего).

Исходное требование волны (оставлено как критерий приёмки): «Забудь про порт» даёт карточку; без карточки ответ не «удалено/сохранено».

### 4.5. M5-F3 — PII-supersede без канала (P1, продуктовое решение)

`blocked_pii` корректно не даёт batch-процессу менять PII-факт без человека, но канала для человека нет: `HitlService.create_tool_approval_card` для `side_effect="write"` требует `org_id`, а `PromotionCandidate` его не несёт. Наблюдаемость уже сделана (отдельный исход, агрегированный warning, метрика/алерт). **Не** обходить HITL и **не** снимать `contains_pii` автоматически.

**Решение владельца:** либо добавить `org_id` в promote-путь и адресовать карточку менеджеру, либо явно оставить PII-supersede ручной admin-операцией с audit. До решения — статус «blocked», не «skipped».

---

## 5. Уже исправленные находки аудита (не переоткрывать)

| ID | Находка | Статус 2026-10-20 |
|---|---|---|
| M5-F1 | `graph_query` без temporal-предиката отдавал expired/superseded факты | исправлено: `assert_fact_read_is_temporal` + `GraphQueryCommand.as_of` + автобинд |
| M5-F1b | `$as_of` упомянут, но предикат неполный | исправлено: три конъюнкта с null-guard на каждый alias `:MemoryFact` |
| M5-F2 | `invalid_at = now()` вместо `valid_at` нового факта | исправлено: valid-time cut; future `invalid_at` не считается неактивным |
| M5-F4 | upsert продлевал PII-retention и снимал `contains_pii` | исправлено: липкий флаг + `LEAST` дедлайна, regression на реальном Postgres |
| M3-E1 | DLQ недостижим при падении воркера | исправлено: `_bury_exhausted_leases` + `attempts < max_attempts` |
| M3-E2 | lease не продлевался, бюджет job > lease | исправлено: heartbeat + `renew()` + проверка владения перед записью; fencing-token — M9 |
| M3-E3 | недетерминированный ключ → дубликаты при retry | исправлено: `add-<sha256(normalized text)>` |
| M3-E4 | Postgres-очередь не покрыта тестами | исправлено: CI `integration-db`, миграции + `PALATIUM_REQUIRE_DB=1` |
| M3-E5 | dedup-контекст без инструкции + prompt injection | исправлено: `Deduplication (mandatory)` + `wrap_untrusted_tool_output` |
| M3-E6 | enqueue не атомарен (IntegrityError/переполнение) | исправлено: advisory lock + `ON CONFLICT` + capacity в INSERT |
| M3-E7 | глобальный `max_queue` без tenant-скоупа | исправлено: fair share + причина отказа (`queue_full`/`tenant_full`) |
| E2E-01 | NL «запомни/забудь» отвечал успехом без записи и без HITL | исправлено (R2.1): отдельная ось `MemoryMutationKind`, ранний выход графа в `NODE_MEMORY_MUTATION`, HITL-карточка `mem-save-*`/`mem-forget-*`, запись только после Approve (§4.4) |
| E2E-03 | NL save 5433 не записался → новый тред не знал значения | исправлено тем же контрактом (R2.1): причина была в отсутствии записи, а не в recall |

---

## 6. План исправления (строго M0–M8)

### Волна R1 — P0, до следующего релиза (M5 + M3)

| # | Работа | Слой | Статус 2026-10-21 |
|---|---|---|---|
| R1.1 | Claim кандидата до graph write; release при ошибке | M3 `MemoryPromotionService` / `PostgresMemoryPort` | **Готово.** `promote_claimed_at` (миграция `k1f2a3b4c5d6`), `claim_promotion`/`release_promotion`, lease `DEFAULT_PROMOTE_CLAIM_SECONDS`; кандидат под активным claim не выдаётся второму промоутеру |
| R1.2 | Neo4j unique constraint `MemoryFact.node_id` + `MERGE` вместо `CREATE` | M5 `Neo4jGraphWritePort` + `neo4j_schema` | **Готово.** Constraint в bootstrap, `MERGE` + `ON CREATE/ON MATCH` в create/supersede, версия при create = `max(all versions)+1` (иначе `MERGE` попадает в забытую ноду) |
| R1.3 | `promoted_at = NULL` при изменении текста/типа | M5 `PostgresMemoryPort.put` | **Готово** (по содержимому факта, не по всему `value`) + in-memory паритет |
| R1.4 | Forget: машинно-читаемый результат по слоям | M3/M5 `memory_tool_ops` + UI | **Переоценено:** E2E-02 снят (§4.2); остаётся R2.4 (forget в треде с прогретым L1) |
| R1.5 | Cleanup дублей `:MemoryFact` | M5 ops | **Готово:** `scripts/dedupe_memory_facts.py` (dry-run по умолчанию, `--execute`, earliest wins, `SUPERSEDES` перевешиваются) |

### Волна R2 — P1 (M1/M2/M4/M5)

| # | Работа | Слой | Критерий готовности |
|---|---|---|---|
| R2.1 | NL-мутация памяти: `MemoryMutationKind` → `search_memory` → HITL `save_memory`/`forget_memory` (см. §4.4) | M1/M2 + 070 | **Готово.** Ось мутации в Intent + ранний выход `NODE_MEMORY_MUTATION` (без worker/formatter), read-check → `MemoryMutationGate` → карточка `mem-save-*`/`mem-forget-*`; запись только после Approve, честный отказ при промахе; карточки не кэшируются; одобренный факт получает `explicit_write` и находится recall'ом в новом треде (E2E-03). Сквозной regression — `tests/integration/test_memory_mutation_turn.py` |
| R2.2 | ~~Канонизация `entry_key`; recall выбирает latest~~ — снято (§4.4: дефект был в отсутствии записи) | — | — |
| R2.3 | PII-supersede: решение `org_id`/admin-канал | M5 + 020 | `blocked_pii` имеет owner и audit; нет авто-флипа |
| R2.4 | Forget в прогретом треде: L1-контекст не отдаёт удалённое | M6/M3 | **Готово.** Fan-out forget: после Approve `MemoryForgetService` читает текст удалённой записи и снимает совпадающие по субъекту слоты `SessionScratchpad` (overlap-политика `MemoryMutationPolicy.shares_subject`); `forgotten`/`graph_expired` уже в ответе `forget_memory`, `scratchpad_cleared` — в результате выполнения. Regression: `tests/unit/test_session_scratchpad.py` + `test_memory_mutation_turn.py::test_forget_turn_clears_the_thread_scratchpad_pin` |

### Волна R3 — P2 (frontend/UX)

| # | Работа | Слой | Критерий готовности |
|---|---|---|---|
| R3.1 | Одинарное экранирование в fenced code | web Markdown | **Готово.** Эскейпинг нормализуется в домене, не в UI: `_verbatim_source` валидатор `CodeBlock.content` → `normalize_code_entities` (2 ограниченных раунда, закрытый набор `quot/apos/#34/#x22/#39/#x27`). Маркдап в коде (`<div …>`) не трогается — регекс не хватает обычные `<`/`>`. Промпт Formatter запрещает HTML-эскейпить код. Regression: `tests/unit/test_content_code_entities.py` (single / double / apostrophe / markup-safe / GFM fence e2e) |
| R3.2 | Сохранение треда в standalone при F5 | web bootstrap | **Готово.** Mock-host handshake в `web/standalone.html` пред-диспатчит контекст при `hostThreadId` в `sessionStorage`, а не только по `?preload`: тред и транскрипт (`/api/sessions/{thread}/turns`) восстанавливаются, `thread-*` не пересоздаётся. Live-проверка: `beforeThread == afterThread`, обе реплики на месте, console чистый; host-режим не затронут (ветка та же, флаг `hasPreload`) |
| R3.3 | 404 статики | web | **Готово.** Inline SVG data-URI `<link rel="icon">` в `index.html` и `standalone.html` — браузер не ходит за `/favicon.ico`. `npm run verify` (tsc/eslint/prettier/vitest, 130 тестов) зелёный; console на load пуст |
| R3.4 | HITL на read-only: только при реальном низком confidence, с причиной | CriticPolicy | **Готово.** `HitlInteractionPolicy` различает *clarification*-турн (`selected_strategy="clarify"` / `task_kind="clarification_needed"`) и уже отвеченный read-only: на отвеченном `requires_user_choice` от Intent не минтит choice-карточку, а фиксируется как `ignored_user_choice` в `HitlCardPlan` + `interaction_plan_log_fields`. Неизвестный `task_kind` остаётся fail-closed (choose-контракт не снимается по догадке). Структурные меню (menu-shaped) по-прежнему минтятся, даже если флаг Intent проигнорирован. Review-карточка называет причину — gate + confidence. Regression: `test_hitl_interaction_policy.py::test_answered_read_only_turn_ignores_over_flagged_choice`, `::test_menu_shaped_choice_still_mints_on_answered_turn`, `test_interaction_assembler.py::test_assembler_delivers_fact_answer_with_over_flagged_choice`, `test_hitl_service.py::test_create_and_resolve_card` |

### Волна R4 — M9 (только eval, флаги OFF)

- Метрики: duplicate rate / near-duplicate rate, Recall@k, p95, supersede-correctness, forget-leak-rate.
- Каждый флаг — отдельный PR: baseline при `false`, порог, rollback, запись в `test_m9_flag_gates.py`.
- Не включать `MEMORY_CROSS_ENCODER_RERANK` до замены lexical stub; не возвращать снятые binary/Hebbian-ручки.

### Соответствие guardrails §7

- **Не** предлагаются Neo4j-only, Qdrant, Redis STM, Celery/Temporal, Mem0/Graphiti как SoT.
- Promote остаётся batch-процессом; extract не вызывает promote.
- Forget — soft-expire + retention, не физическое удаление истории.
- Новые поля/claim-механизм — в существующих PostgreSQL/Neo4j, без второго store.
- Skill-write без HITL не предлагается.

---

## 7. Регрессионный набор

| Тест | Что фиксирует | Статус |
|---|---|---|
| `tests/integration/test_memory_promotion_claim.py` (new) | claim — compare-and-set; lease; `mark_promoted` снимает claim; reset/сохранение `promoted_at` | зелёный (5/5 на стенде) |
| `tests/unit/test_memory_promotion.py` | два промоутера → одна запись; claim эксклюзивен; перезапись текста возвращает кандидата | зелёный |
| `tests/unit/test_neo4j_graph_write_port.py` | `MERGE`/`ON MATCH` не переписывает lifecycle; create после forget — version `max+1` | зелёный |
| `tests/integration/test_memory_postgres_retention.py` | PII-инварианты upsert (не регрессировали) | зелёный |
| `tests/eval/test_m9_flag_gates.py` | ни один флаг не включён без метрики | зелёный |
| `tests/integration/test_memory_mutation_turn.py` (new, R2.1) | «запомни/забудь» — ход графа: карточка вместо успеха, запись/удаление только после Approve, reject не пишет, промах forget — честный отказ без карточки | зелёный (4/4) |
| `tests/unit/test_memory_mutation_gate.py` (new, R2.1) | read-check, supersede существующего ключа, честный пустой forget, отказ без владельца/payload | зелёный |
| `tests/unit/test_memory_mutation_routing.py` (new, R2.1) | coercion оси мутации в Intent JSON, `route_after_intent` → `memory_mutation` | зелёный |
| `tests/unit/test_response_cache.py` | ответ с `hitl_cards` не попадает в L1 (мёртвая карточка не переигрывается) | зелёный |
| `tests/unit/test_memory_recall.py` | маркер `explicit_write`: одобренный факт переживает новый тред, выведенный extract'ом — нет (P0-B) | зелёный |
| `tests/unit/test_session_scratchpad.py` | fan-out forget снимает слоты про удалённый субъект, не трогает чужие (общий глагол ≠ субъект); supersede снимает пин старого значения, оставляет идентичный | зелёный |
| `tests/unit/test_content_code_entities.py` (new, R3.1) | `&quot;`/`&amp;quot;`/`&apos;`/`&#39;` в fenced code декодируются один раз; `<div …>` в коде не трогается; e2e через GFM-парсер | зелёный (8/8) |
| `tests/unit/test_hitl_interaction_policy.py` (R3.4) | отвеченный read-only турн с `requires_user_choice` → без choice-карточки (`ignored_user_choice`); menu-shaped меню минтится и там; неизвестный `task_kind` — fail-closed | зелёный |
| `tests/unit/test_interaction_assembler.py` (R3.4) | тот же кейс на уровне assembler: `invalid=False`, документ доставлен, `interaction` снят | зелёный |
| Playwright `s1`–`s8` | стриминг, Markdown, L1/L2, save/HITL, F5, supersede, forget, isolation, edge-cases | прогон аудита |

**Exit criteria для R1:** M5-F5, M5-F6 закрыты на живом стенде (`alembic upgrade head` + `dedupe_memory_facts.py --execute`, затем повторный конкурентный promote даёт одну ноду); в `memory.entries` и Neo4j нет расхождения по `entry_key`.

### Статус на 2026-10-21 (что уже в коде)

| Изменение | Файлы |
|---|---|
| Claim кандидата, lease, release, `mark_promoted` снимает claim | `domain/memory/promotion.py`, `domain/memory/promotion_port.py`, `application/services/memory_promotion.py`, `infrastructure/memory/{postgres_memory_port,in_memory_store}.py` |
| Колонка `promote_claimed_at` | `alembic/versions/k1f2a3b4c5d6_memory_promote_claim.py`, `infrastructure/database/models/memory_entry.py` |
| `promoted_at` следует за содержимым | `infrastructure/memory/postgres_memory_port.py` (`ON CONFLICT`), `in_memory_store.py` |
| `MERGE` + версия `max+1` + in-memory паритет | `infrastructure/graph/{neo4j_graph_write_port,in_memory_graph_write_port}.py` |
| Unique constraint `MemoryFact.node_id` | `infrastructure/memory/neo4j_schema.py` |
| Дедуп существующих нод | `scripts/dedupe_memory_facts.py` |
| Ось мутации памяти + coercion | `domain/policies/types.py`, `domain/agents/intent.py`, `application/agents/intent_classifier/{parsing,prompts}.py`, `domain/policies/memory_mutation.py` |
| Ранний выход графа + агентless-узел | `application/orchestration/{nodes,graph,agent_registry}.py`, `core/types/graph_nodes.py`, `core/observability/span_names.py` |
| HITL-стейджинг мутации | `application/services/memory_mutation.py`, `intent_graph_runner.py` (сохранение карточек), `response_cache_service.py` |
| Fan-out мутаций на thread-scratchpad | `application/services/{memory_forget_service,memory_save_service,session_scratchpad}.py`, `domain/policies/memory_mutation.py` |
| Recall одобренного факта (`explicit_write`) | `application/services/{memory_save_service,memory_recall}.py`, `domain/memory/types.py` |
| Единый инстанс save/forget + gate | `application/{wiring,bootstrap}.py` |
| Нормализация HTML-сущностей в коде (R3.1) | `domain/content/{code_text,content_document}.py`, `application/agents/formatter/prompts.py` |
| Гейт choice-карточек на отвеченном read-only турне (R3.4) | `domain/hitl/{interaction_policy,option_synthesis}.py`, `application/services/{interaction_assembler,hitl_service}.py` |
| Inline favicon + standalone reload по `hostThreadId` (R3.2/R3.3) | `web/{index.html,standalone.html}` |

**Миграция применена на стенде** (`alembic upgrade head`: `j0e1f2a3b4c5 → k1f2a3b4c5d6`), integration-тесты claim прошли 5/5.

**Требуется человек (осознанно не автоматизировано):** `uv run python scripts/dedupe_memory_facts.py --execute` и перезапуск API. Dry-run на стенде нашёл ровно одну группу — `node_id=26d42a70d58bef4dbbf009e2`, 2 копии; это тот самый дубль из §4.1. Удаление узла графа — history-affecting операция, её выполняет владелец стенда. Пока дубли есть, bootstrap пишет `neo4j.schema_bootstrap.constraint_failed` с подсказкой — ожидаемое поведение, а не тихий пропуск; constraint создастся сам при следующем старте после дедупа.

---

## 8. Ограничения аудита

- Playwright-прогон — на локальном стенде; production-конфигурация `GRAPH_QUERY_BACKEND`/embedding gateway не проверялась.
- **Исправление первой редакции:** `E2E-02` был классифицирован как P0 по прогону, в котором клик «Забыть» упал по таймауту и forget не выполнялся (§4.2). Отдельный прогон с раскрытой панелью и проверка `memory.entries` показали, что forget работает. Вывод «дефекта нет» — тоже результат проверки, а не ослабление критерия.
- `E2E-01`/`E2E-03` переклассифицированы: причина — отсутствие интерактивной мутации памяти, а не ошибка маршрутизации или recall.
- M5-F6 воспроизведён при конкурентном promote (плановый job + ручной CLI); частота в production зависит от расписания и дисциплины ручных запусков.
- Integration-тесты R1 прогнаны против живой БД после `alembic upgrade head` (5/5 + retention/search 3/3). Не проверено на живом Neo4j: constraint нельзя создать, пока существует дубль, а его удаление — операция владельца стенда (`dedupe_memory_facts.py --execute`).
- Оценка флагов M8 — дизайн, не измерение: baseline для части флагов ещё не снят.

# Верификация M5 — bi-temporal long-term cortex

**Дата:** 2026-10-20
**Волна:** M5 (`.cursor/plans/memory-max-pro.md` §6)
**Основание:** ADR 0004 (hybrid memory), §0.3 pre-flight (B5), 060.
**Метод:** статическое чтение кода Palatium + сверка с эталоном Graphiti по закреплённым коммитам.
Live-прогон против Neo4j не выполнялся (нет стенда в этом окружении) — все выводы по коду и unit-тестам.

Внешние источники (локальные read-only клоны, `<repo>@<sha>`):

| Источник | Commit | Дата коммита |
|---|---|---|
| `getzep/graphiti` | `3cc723cd292eb5c2ac5ea2c5539270b8e1b6389f` | 2026-10-20 |
| `mem0ai/mem0` | `0724291bd864cf807e88ee8981c8226644e8fb42` | 2026-10-14 |

> `letta-ai/letta@main` код памяти не содержит (41 файл, README/политики); V1-сервер живёт в ветке `archive`, текущий рантайм — `letta-ai/letta-code`. Для M5 сверка с Letta не даёт эталона bi-temporal: у Letta нет valid-time, есть только paging/eviction. Поэтому A.3 сведён к проверке гарантий сохранности, а не к сравнению полей.

---

## 1. Карта кода M5

| Файл | Ответственность |
|---|---|
| `src/palatium_ai/domain/policies/graph_fact.py` | `GraphFactPolicy.decide_write` — чистое решение create / refresh / supersede / blocked_pii |
| `src/palatium_ai/domain/graph/temporal.py` | `ACTIVE_FACT_AS_OF_PREDICATE`, `is_fact_active_as_of`, `EXPIRED_AT_SENTINEL` |
| `src/palatium_ai/infrastructure/graph/neo4j_graph_write_port.py` | Cypher-шаблоны `_FIND_ACTIVE` / `_REFRESH` / `_SUPERSEDE` / `_CREATE` / `_EXPIRE` / `_LIST_ACTIVE`, upsert, expire |
| `src/palatium_ai/infrastructure/graph/in_memory_graph_write_port.py` | Та же семантика для тестов (эталон поведения без Neo4j) |
| `src/palatium_ai/domain/graph/write_port.py` | `GraphFactUpsert` / `GraphFactRecord` / `GraphWritePort` |
| `src/palatium_ai/application/services/memory_promotion.py` | Единственный продюсер `GraphFactUpsert` (batch promote) |
| `src/palatium_ai/infrastructure/mcp/memory_tool_ops.py` | `forget_memory` → fan-out `expire_fact` |
| `src/palatium_ai/infrastructure/graph/neo4j_graph_port.py` | `graph_query` — параметризованный read-only Cypher |
| `tests/unit/test_neo4j_graph_write_port.py`, `tests/unit/test_graph_fact_temporal.py` | Контрактные тесты M5 |

---

## 2. Сверка с Graphiti

| Аспект | Graphiti | Palatium M5 | Расхождение | Вердикт |
|---|---|---|---|---|
| Набор bi-temporal полей на факте | `valid_at` / `invalid_at` / `expired_at` / `reference_time` (`edges.py:271-285`) | `valid_at` / `invalid_at` / `expired_at` + `created_at`; `reference_time` нет | Паритет по осям valid/system; источника эпизода-времени нет | оставить |
| System-time sentinel | `invalid_at`/`expired_at` = NULL допустим | `expired_at` = `9999-12-31T23:59:59Z` (Neo4j не индексирует отсутствующее свойство) | Техническое, не семантическое | оставить |
| Решение «какой факт инвалидировать» | Кандидаты сортируются по `valid_at`; более поздний вытесняет (`edge_operations.py:731-745`) | Активный факт ищется по `entry_key` + `version DESC` (`_FIND_ACTIVE_CYPHER`), вытесняется всегда он | Graphiti сравнивает интервалы, Palatium — версии одной записи | оставить (модель «одна запись = один ключ», а не свободный граф фактов) |
| Что пишется в `invalid_at` старого факта | `edge.invalid_at = resolved_edge.valid_at` — момент, когда новый факт стал истинным | `SET old.invalid_at = datetime()` — момент записи | **F2** | M9-candidate |
| Защита от silent overwrite | Новый факт + инвалидация, старый не перезаписывается | `supersede` создаёт новый узел + `SUPERSEDES`; `refresh` (только при равном тексте) не трогает `text` (`_REFRESH_CYPHER`) | нет | подтверждено |
| Противоречие с PII | Нет аналога | `blocked_pii` — запись не выполняется, HITL-пути нет | **F3** | M9-candidate |
| `as_of`-выборка | Фильтр по `valid_at`/`invalid_at` в запросах | `ACTIVE_FACT_AS_OF_PREDICATE` + `_LIST_ACTIVE_CYPHER` | Паритет по предикату | подтверждено |
| Применение предиката на read-пути | Внутри библиотеки — запросы строит код Graphiti | `graph_query` принимает Cypher от агента; предикат только рекомендован в описании tool'а | **F1** | M5-bug |

### Подтверждённые гарантии

1. **Нет silent overwrite.** Разные тексты при активном факте → `supersede` (`graph_fact.py:32-34`);
   старый узел не редактируется. `refresh` применяется только при совпадении текста и меняет
   `importance`/`confidence`/`updated_at`, но не `text` (`neo4j_graph_write_port.py:31-36`).
2. **Forget fan-out.** `forget_memory` при успешном medium-forget вызывает
   `GraphWritePort.expire_fact` (`memory_tool_ops.py:298-310`), который проставляет `expired_at`
   **всем** версиям `(user_id, entry_key)` (`_EXPIRE_CYPHER`; in-memory — цикл по всем
   `_index[key]`). Orphan «живых» фактов после forget не остаётся.
3. **История сохраняется.** `expire_fact` — soft-expire, узлы и `SUPERSEDES`-рёбра остаются,
   `as_of`-запросы исключают их предикатом. Откат/аудит возможен.
4. **Temporal Select.** `_LIST_ACTIVE_CYPHER` фильтрует valid-time ∩ system-time через
   `datetime($as_of)` (сравнение строк дало бы пустой результат — комментарий в `temporal.py:17-19`
   фиксирует причину).

### Находки

**F1 — `graph_query` fail-open по bi-temporal фильтру. Классификация: `M5-bug`.**

`Neo4jGraphPort.query` (`neo4j_graph_port.py:109-127`) принудительно подставляет только
`$user_id` и прогоняет `assert_graph_query_safe` (read-only + tenant scope). Предикат
`ACTIVE_FACT_AS_OF_PREDICATE` не инжектируется и нигде, кроме тестов, не применяется —
он существует как константа и как подсказка в описании инструмента
(`tool_policy.py:219-221`, `platform_schemas.py:162`).

Следствие: агент, написавший `MATCH (f:MemoryFact) WHERE f.user_id = $user_id RETURN f.text`,
получит **superseded и expired** факты. То есть `forget_memory` перестаёт быть забыванием для
любого read-пути, который не повторил предикат вручную — прямое нарушение инварианта 060
«forget medium должен согласовываться с long-term». Тест `test_graph_fact_temporal.py:177`
предикат подставляет сам, поэтому зелёный и не ловит регрессию.

Контрмера (в рамках M5, отдельный PR): гарантия на уровне порта, а не текста описания.
Предпочтительный вариант — поддерживаемый при записи label `:MemoryFactActive` (снимается в
`supersede`/`expire`), чтобы корректный `MATCH` был короче некорректного; альтернатива —
обязательный `$as_of` в `GraphQueryCommand` и отказ (типизированная ошибка, 035) на запрос
к `MemoryFact` без предиката.

**Статус (2026-10-20): исправлено (fail-closed guard, без миграции данных).**
Выбран вариант с обязательным `$as_of`: `assert_fact_read_is_temporal` в
`cypher_safety.py` — часть единственного choke point `assert_graph_query_safe` — отказывает
на `:MemoryFact` без `$as_of` и возвращает агенту текст канонического предиката;
`GraphQueryCommand.as_of` + `as_of_param_value` биндят `$as_of` в обоих портах
(`Neo4jGraphPort`, `InMemoryGraphPort`, по умолчанию now). Description `graph_query`
(`platform_schemas.py`, `tool_policy.py`) приведён к «refused» вместо «recommended».
Regression: `tests/unit/test_graph_web_mcp.py` (guard + tool-level `is_error`) и
`tests/unit/test_neo4j_graph_port.py` (автобинд `$as_of`, отказ до драйвера).

Остаточная граница: наличие `$as_of` в тексте не доказывает, что предикат написан целиком —
гарантия закрывает исходный fail-open (запрос без времени), но не «время привязано, фильтры
не все».

**Статус F1b (2026-10-20): закрыто тем же choke point, без label и миграции данных.**
`assert_fact_read_is_temporal` больше не проверяет «`$as_of` где-то упомянут»: для **каждого**
alias'а, связанного с `:MemoryFact`, требуется весь предикат — три конъюнкта
`valid_at <= datetime($as_of)`, `invalid_at > datetime($as_of)`, `expired_at > datetime($as_of)`,
каждый под `IS NULL OR` (без null-guard'а `NULL <= x` даёт NULL, и факты с открытой границей
молча исчезают). Сопоставление семантическое, не «побайтовое»: alias, регистр и пробелы
свободны, поэтому корректный запрос с любым именем узла проходит, а
`WHERE $as_of IS NOT NULL` и односторонний valid-time — нет. Анонимный `(:MemoryFact)`
отклоняется: без alias предикат нечем проверить.

Почему не label `:MemoryFactActive` (вариант из контрмеры): label требует инварианта на **каждом**
переходе записи (promote, supersede, expire, backfill существующих узлов) и при пропуске
перехода теряет факты молча — цена ошибки выше, чем у fail-closed guard'а на чтении. Label
остаётся возможной оптимизацией «короче корректный запрос», но не заменой проверки.

Намеренное следствие: запрос исторических (superseded) фактов через `graph_query` теперь
невыразим. Это осознанный fail-closed: история — предмет promote/inspection-job'ов, а не
read-пути агента (иначе `forget_memory` снова перестаёт быть забыванием).

Regression: `test_graph_query_accepts_the_predicate_under_any_alias`,
`test_graph_query_rejects_partial_temporal_predicates` (3 формы),
`test_graph_query_rejects_anonymous_fact_node`,
`test_graph_query_requires_the_predicate_on_every_fact_alias` (`tests/unit/test_graph_web_mcp.py`).

**F2 — `invalid_at` берётся из системного времени записи, а не из valid-time нового факта. Классификация: `M9-candidate`.**

`_SUPERSEDE_CYPHER` (`neo4j_graph_write_port.py:62`) ставит `old.invalid_at = datetime()`,
Graphiti — `edge.invalid_at = resolved_edge.valid_at` (`edge_operations.py:779`).

Сегодня это **не наблюдаемо**: единственный продюсер `GraphFactUpsert`
(`memory_promotion.py:82-95`) не передаёт `valid_at`, поэтому он равен моменту записи и обе
величины совпадают. Расхождение проявится при backdated-записи (импорт истории, `valid_at` из
эпизода): для `as_of` внутри `[new.valid_at, now)` оба факта окажутся активными, и recall
вернёт противоречащие тексты (дедуп в `memory_recall` идёт по тексту, а не по `entry_key`).
Условие возврата к вопросу: любая волна, вводящая `valid_at` из источника.

**Статус (2026-10-20): исправлено до появления продюсера `valid_at` — пока правка локальна.**
Почему сейчас, а не «когда появится продюсер»: `GraphFactUpsert.valid_at` уже часть контракта
порта, то есть backdated-запись **уже выразима**, а дефект — нет: он живёт в би-temporal
инварианте, а не в потребителе. Исправление на два оператора, после первого backdated-продюсера
оно превратилось бы в миграцию уже противоречивых данных.

Сделано: `_SUPERSEDE_CYPHER` и `InMemoryGraphWritePort` ставят `invalid_at` = `valid_at`
**нового** факта (valid-time cut: старый перестаёт быть истинным там, где новый начинает).
Одновременно `_FIND_ACTIVE_CYPHER` перестал считать «active» через `invalid_at IS NULL`:
будущий (запланированный) supersede оставлял текущий факт невидимым для следующей записи, и
следующий upsert делал `CREATE` вместо `SUPERSEDE` — та же ключ, две живые версии. Теперь
условие временное (`invalid_at > datetime()`), как в `_LIST_ACTIVE_CYPHER`.

Следствие, которое теперь корректно: `valid_at` в будущем оставляет старый факт активным до
этого момента и не создаёт «дыру», в которой не активен ни один факт.

Regression: `test_supersede_cuts_valid_time_at_the_new_fact_not_at_now`,
`test_find_active_treats_a_future_invalid_at_as_still_current`
(`tests/unit/test_neo4j_graph_write_port.py`), `test_backdated_supersede_has_no_overlap_window`
(`tests/unit/test_graph_fact_temporal.py`).

**F3 — `blocked_pii` не имеет пути разрешения. Классификация: `M9-candidate`.**

`GraphFactPolicy.decide_write` при `contains_pii=True` и изменившемся тексте возвращает
`blocked_pii`; `Neo4jGraphWritePort` возвращает пустой `node_id`; `memory_promotion` пишет
warning `memory_promotion.blocked_pii_supersede` и считает кандидата непромоутнутым
(`memory_promotion.py:96-102`). HITL-карточки и повторной попытки нет — противоречащий
PII-факт остаётся в L4 устаревшим навсегда.

Это корректная граница 020 (batch не флипает PII автоматически), но не «решение»: у оператора
нет канала применить подтверждённое изменение. Кандидат M9 — HITL-карточка на PII-supersede
с идемпотентным resume, без снятия запрета на авто-флип.

**Статус (2026-10-20): канал не сделан — и это блокировано продуктовым решением, а не кодом.**
`HitlService.create_tool_approval_card` для `side_effect="write"` **требует `org_id`**
(`hitl_service.py:262-266`), а `PromotionCandidate` его не несёт: promote-batch идёт per
`user_id`, `org_id` в medium-строке нет. Значит карточку невозможно адресовать в очередь
менеджера, не выдумав «чей org» и «кто аппрувит» — это решение владельца, а не вывод из кода
(001). Возврат к вопросу: любая волна, добавляющая `org_id` в promote (или орг-очередь HITL).

Что сделано вместо тишины — состояние перестало быть невидимым и перестало спамить:
`blocked_pii` больше не `False` наравне с «policy skip», а отдельный исход
`PromoteOutcome = Literal["promoted", "skipped", "blocked_pii"]`; `run_batch` агрегирует его
**одним** warning'ом на батч (`blocked`, первые 5 `entry_keys`, флаг усечения) и публикует
`palatium_memory_promote_blocked_pii_total`. Это не ошибка: promote сделал ровно то, что должен,
поэтому серия отдельная от `palatium_memory_promote_errors_total` — иначе вечный алерт об
ошибках при отсутствии поломки. Алерт — `PalatiumMemoryPromoteBlockedPii` (`info`).

Почему агрегация, а не «просто пометка»: кандидат ретраится каждый батч, пока он не промоутнут,
так что per-candidate warning рос без границы. Aggregation делает серию читаемой как «сколько
фактов застряло», что и есть реальный вопрос оператора.

Regression: `test_blocked_pii_supersede_is_counted_once_per_batch`,
`test_try_promote_reports_blocked_pii_distinctly_from_a_skip`
(`tests/unit/test_graph_fact_temporal.py`).

**F4 — upsert продлевает PII-retention и снимает `contains_pii`. Классификация: `M5-bug`.**

`RetentionPolicy.memory_expires_at` документирует контракт «PII clock = created_at only, access
does not extend PII» (`retention.py:146-153`). `PostgresMemoryPort.put` его нарушал: на
`ON CONFLICT` `expires_at` пересчитывался от `now`, то есть каждое пересохранение существующей
PII-строки отодвигало дедлайн на полное окно. Второй, более грубый путь — `contains_pii`
перезаписывался входящим значением: строка, один раз классифицированная как PII, при следующей
записи без флага становилась medium и получала 30-дневное окно вместо 90-дневного PII.

Почему это не косметика: retention удаляет **по `expires_at`**
(`MemoryRetentionHandler._delete_expired`), другого механизма забывания у medium нет. Значит оба
пути означают «PII-строка не будет удалена никогда», пока её переписывают — а переписывает её
ровно тот же extract, который и создал.

Проверка чувствительности (старый код, реальный Postgres): дедлайн `+1 день` после пересохранения
стал `+90 дней`, флаг после записи без него — `false`.

Исправлено 2026-10-20 в conflict-ветке, атомарно (без read-then-write гонки):

- `contains_pii = existing OR excluded` — **липкий**: расPIIфикация возможна только явным
  retention/anonymise-действием, а не побочным эффектом следующей записи (020: fail-closed);
- `expires_at = CASE WHEN pii THEN LEAST(existing, excluded) ELSE excluded END` — PII-строка
  (до или после записи) никогда не получает более поздний дедлайн; `least` игнорирует NULL,
  поэтому legacy-строки без срока получают входящий.
- non-PII поведение сохранено намеренно: активность легитимно продлевает medium/episode-окно.

Regression: `tests/integration/test_memory_postgres_retention.py` (реальный Postgres —
`ON CONFLICT` semantics иначе не проверить: fake-session проверяет форму запроса, а не поведение).

---

## 2.1. Live-аддендум 2026-10-21 (E2E-стенд)

При живом прогоне UI на локальном стенде (PostgreSQL + pgvector + Neo4j) обнаружены два
дефекта, которых не было в статическом аудите 2026-10-20. Оба воспроизведены на реальных
данных, не в in-memory двойнике.

**F5 — `promoted_at` не сбрасывается при изменении medium-строки. `M5-bug`.**

`PostgresMemoryPort.put` в conflict-ветке обновляет `value`, `search_text`, `importance`,
embedding и PII/expiry, но не `promoted_at`. `list_promotion_candidates` фильтрует
`promoted_at IS NULL`; после первого promote изменение текста в medium больше никогда не
доходит до L4. Проверка: строка `qa_port_1792572741690` promoted в 08:55, текст изменён на
`…5434`, `promoted_at` остался, активный `:MemoryFact` — `…5433`.

**F6 — конкурентный promote создаёт дубликаты активных `:MemoryFact`. `M5-bug`.**

`_CREATE_CYPHER` делает `CREATE`, а не `MERGE`; уникального constraint на `node_id` нет;
`run_batch` не claim'ит кандидата атомарно. Плановый promote и ручной `memory_promote`
одновременно прошли `_FIND_ACTIVE` и создали две ноды с одинаковым `node_id`
(`26d42a70d58bef4dbbf009e2`), `entry_key`, `version=1`; обе активны (`invalid_at=NULL`,
`expired_at=9999-12-31`), созданы с разницей 5 мс. Это нарушает инвариант «один активный факт
на `(user_id, entry_key)`» и делает recall недетерминированным.

Оба дефекта отражены в [`e2e-bug-report.md`](e2e-bug-report.md) как `M5-F5` / `M5-F6` и
**исправлены 2026-10-21**: claim кандидата до graph write (lease, release при не-успехе),
Neo4j unique constraint на `node_id` + `MERGE`, сброс `promoted_at` по изменению содержимого
факта. Операционное требование: `alembic upgrade head` (колонка `promote_claimed_at`) и
`scripts/dedupe_memory_facts.py --execute` перед созданием constraint на стенде с уже
существующими дублями.

---

## 3. Границы аудита

- Статический аудит 2026-10-20 не поднимал Neo4j: F1 подтверждён по коду порта и схеме
  инструмента. Live-аддендум 2026-10-21 закрыл эту границу для F5/F6; индексы и plan-ы
  `graph_query` по-прежнему не измерялись.
- Ops-часть M5 (`GRAPH_QUERY_BACKEND=neo4j` в prod, миграции, retention фактов) вне этого аудита.
- `letta-ai/letta-code` не разбирался: там иная модель памяти (файлы/блоки), к bi-temporal M5
  прямого отношения не имеет.

## 4. Сводка классификации

| ID | Находка | Класс | Действие |
|---|---|---|---|
| F1 | `graph_query` без bi-temporal фильтра отдаёт expired/superseded факты | `M5-bug` | **исправлено** 2026-10-20 (fail-closed guard + автобинд `$as_of`) |
| F1b | `$as_of` упомянут, но предикат неполный (fail-open) | `M5-bug` | **исправлено** 2026-10-20 (guard требует все 3 конъюнкта с null-guard'ом на каждый alias) |
| F2 | `invalid_at` = системное время, а не `valid_at` нового факта | `M9-candidate` | **исправлено** 2026-10-20 (valid-time cut; FIND больше не считает будущий `invalid_at` неактивным) |
| F3 | PII-supersede блокируется без HITL-канала | `M9-candidate` | **наблюдаемость сделана** 2026-10-20 (отдельный исход + агрегированный warning + метрика/алерт); HITL-карточка заблокирована отсутствием `org_id` в promote — продуктовое решение |
| F4 | Upsert продлевает PII-retention и снимает `contains_pii` (обход forgetting) | `M5-bug` | **исправлено** 2026-10-20 (conflict-ветка: липкий флаг + `LEAST` дедлайна; regression на реальном Postgres) |
| F5 | `promoted_at` не сбрасывается при изменении medium → L4 навсегда устаревает | `M5-bug` | **исправлено** 2026-10-21 (`ON CONFLICT` сбрасывает маркер по изменению текста/типа; in-memory паритет; `e2e-bug-report.md` §6 R1.3) |
| F6 | Конкурентный promote создаёт дубликаты активных `:MemoryFact` с одним `node_id` | `M5-bug` | **исправлено** 2026-10-21 (claim до graph write + lease, `MERGE` + unique constraint, версия `max(all)+1` при create, `scripts/dedupe_memory_facts.py`; §6 R1.1–R1.2, R1.5) |

§7-reject в этой фазе не сработал: ни одна находка не требует смены SoT, второго store или
Celery/Temporal. Все шесть — усиление существующего решения, как и предполагает §7 плана.

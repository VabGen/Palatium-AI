# Верификация M3 — durable extract (`SKIP LOCKED`)

**Дата:** 2026-10-20
**Волна:** M3 (`.cursor/plans/memory-max-pro.md` §6)
**Основание:** ADR 0002 (out-of-band jobs), ADR 0003 (checkpointer TTL), §0.3 pre-flight (B3, B7), 060.
**Метод:** статическое чтение кода + сверка с Mem0 (extract-at-write) и Letta (sleep-time).
SQL-путь `PostgresExtractJobQueue` на момент аудита не был покрыт тестами (E4), поэтому выводы
E1–E4 получены чтением кода; при исправлении E1 (2026-10-20) поведение SQL воспроизведено на
одноразовом Postgres 18 и закреплено интеграционными тестами.

Внешние источники (read-only клоны):

| Источник | Commit | Дата коммита |
|---|---|---|
| `mem0ai/mem0` | `0724291bd864cf807e88ee8981c8226644e8fb42` | 2026-10-14 |
| `letta-ai/letta` (ветка `archive`, V1) | `56ba9c25552605eec89de8ed3dc6394b625c1993` | 2026-08-13 |

> Актуальный Mem0 OSS перешёл на **ADD-only** извлечение с `linked_memory_ids`
> (`mem0/configs/prompts.py:468-515`), а не на ADD/UPDATE/DELETE: операции UPDATE/DELETE остались
> в `DEFAULT_UPDATE_MEMORY_PROMPT` (`:176-185`) и в v3-пути `_add_to_vector_store` не используются.
> Сверка ниже ведётся с фактическим v3-поведением, а не с описанием «двухфазный ADD/UPDATE/DELETE».

---

## 1. Карта кода M3

| Файл | Ответственность |
|---|---|
| `src/palatium_ai/domain/memory/extract_queue.py` | Порт `ExtractJobQueuePort`, `ExtractJobRecord`, `ExtractQueueStats` |
| `src/palatium_ai/infrastructure/memory/extract_job_queue.py` | `InMemoryExtractJobQueue` (тесты) и `PostgresExtractJobQueue` (`FOR UPDATE SKIP LOCKED`) |
| `src/palatium_ai/infrastructure/database/models/memory_extract_job.py` | ORM `memory.extract_jobs`, `uq_memory_extract_jobs_thread_task`, индекс claim-а |
| `src/palatium_ai/application/services/memory_extract.py` | `MemoryExtractService`: enqueue + worker loop, классификация ошибок, метрики |
| `src/palatium_ai/application/services/memory_fact_persistence.py` | Запись фактов через MCP `save_memory`, ключ `entry_key` |
| `src/palatium_ai/application/services/memory_extract_hitl_service.py` | HITL-карточка перед enqueue (TTL 5 мин) |
| `src/palatium_ai/jobs/memory_promote.py` | Отдельный one-shot/CronJob promote (ось promote) |
| `src/palatium_ai/jobs/memory_consolidate.py` | Sleep consolidation: promote + retention, тоже вне extract |
| `tests/unit/test_memory_extract_queue.py`, `tests/eval/test_memory_failure_modes_m7.py` | Контракт очереди и G1 DoD |

---

## 2. Сверка гарантий

| Гарантия | Mem0 (OSS v3) | Letta (V1, sleep-time) | Palatium M3 | Расхождение | Вердикт |
|---|---|---|---|---|---|
| Идемпотентность enqueue | Нет очереди: `add()` — синхронный вызов, повтор = новая запись | Фоновый агент + `turns_counter`/`last_processed_message_id` (`group_manager.py:258-284`) — прогресс отмечается после обработки | Уникальный `(thread_id, task_id)` + идемпотентный `enqueue` (`extract_job_queue.py:187-217`) | — | подтверждено |
| Идемпотентность обработки | — (нет retry) | Обработка по watermark: повторный проход не переобрабатывает уже отмеченные сообщения | Нет: повторный claim переобрабатывает job, а ключ факта содержит `uuid4` | **E3** | M3-bug |
| Retry / backoff | Нет: ошибка LLM перевыбрасывается (`main.py:962-971`), fallback — на вызывающем | Нет встроенного retry (отдельный агент, ошибки — в лог) | `fail()`: backoff 5s·2^(n-1), `max_attempts` | — | подтверждено |
| DLQ | — | — | `status='dead'` + гейдж `palatium_memory_extract_dead_letter_total` | Недостижим при crash-loop | **E1** | M3-bug |
| Crash worker (kill -9 / OOM) | — | watermark не сдвинут → повторная обработка | Lease истекает → reclaim тем же job_id (`test_lease_expiry_allows_redelivery_without_dup_row`) | Нет продления lease | **E2** | M3-bug |
| Ёмкость очереди | — | — | `max_queue=256` + fair-share доля владельца (`max_queue // 4`), отказ в том же INSERT под advisory lock | — | исправлено (**E6/E7**) |
| Дедуп против уже сохранённого | `Existing Memories` + «primary deduplication reference», `linked_memory_ids` (`prompts.py:502-515`) | Core/recall blocks редактируются агентом (не dedupe) | `existing_memories` fenced + контракт `Deduplication (mandatory)` (`prompts.py`) | **E5** | исправлено (промпт + baseline-метрика) |
| Разделение осей extract / promote | — | consolidation — отдельный агент | Promote только `jobs/*`; в `MemoryExtractService` нет зависимости на promotion | — | подтверждено |

### Подтверждённые гарантии

1. **Идемпотентный enqueue.** `(thread_id, task_id)` уникален; повторный enqueue не создаёт второй
   job, `dead`-job переводится в `pending` с обнулением попыток (ручной replay по тому же turn).
2. **Оси разведены.** `MemoryExtractService.__init__` не принимает `MemoryPromotionService`;
   `memory_fact_persistence` пишет только через `save_memory`; график растёт исключительно из
   `jobs/memory_promote.py` / `jobs/memory_consolidate.py`. Тест
   `test_extract_worker_does_not_call_promote` фиксирует отсутствие `_maybe_promote` / `_promotion`.
3. **SKIP LOCKED-запрос корректен по форме.** `UPDATE ... WHERE id = (SELECT ... FOR UPDATE SKIP
   LOCKED LIMIT 1)` выполняется одной транзакцией, поэтому блокировка подзапроса удерживается до
   конца UPDATE; два воркера не получат одну строку одновременно.
4. **Классификация ошибок воркера.** Schema-ошибки (нет таблицы/колонки) останавливают воркер
   после 5 подряд, connectivity — backoff до 60 с (`memory_extract.py:44-72, 174-231`);
   есть тест `test_extract_worker_stops_on_missing_table`.

---

## 3. Находки

**E1 — DLQ недостижим для job, который роняет воркер. `M3-bug`.**

`claim()` выбирает строки без условия на число попыток: `status='pending' AND available_at<=now`
либо `status='running' AND leased_until<now` (`extract_job_queue.py:228-247`; in-memory — `:87-95`).
Перевод в `dead` есть только в `fail()` (`:285-299`), а `fail()` вызывается из воркера при
**пойманном** исключении (`memory_extract.py:161-173`). Если процесс убит (OOM, SIGKILL при
деплое, зависание дольше lease), `fail()` не исполняется: job реклеймится, `attempts`
инкрементируется при каждом claim, `max_attempts` не проверяется, `dead` не наступает никогда.

Следствия: poison-job крутится вечно (событие «crash-loop»), `attempts` растёт без границы,
а метрика `palatium_memory_extract_dead_letter_total` остаётся нулевой — алерт на DLQ молчит
именно в том сценарии, ради которого DLQ заведён.

Контрмера: в claim-выборку добавить `attempts < max_attempts`, а просроченные `running` с
исчерпанными попытками переводить в `dead` отдельным оператором (в той же транзакции, по
`leased_until < now`). Regression-тест — на Postgres-очереди (см. E4), не на in-memory.

**Статус (2026-10-20): исправлено.** `PostgresExtractJobQueue.claim` вызывает
`_bury_exhausted_leases` в той же транзакции (переход в `dead` с `last_error`), сама claim-выборка
получила `attempts < max_attempts`; in-memory двойник выровнен
(`_bury_exhausted_locked`). Regression: `test_expired_lease_with_exhausted_attempts_moves_to_dead_letter`
(unit) + `test_expired_lease_with_exhausted_attempts_goes_dead` (Postgres). SQL проверен на живом
Postgres 18: без guard'а тот же UPDATE возвращает строку (вечный retry), с guard'ом — 0 строк и
`status='dead'`.

**E2 — Lease не продлевается и не связан с бюджетом job. `M3-bug`.**

`_DEFAULT_LEASE_SECONDS = 300` (`extract_job_queue.py:21`), продления (heartbeat/renew) в порте и
реализациях нет. Бюджет одного job при этом не ограничен 300 с: `execute_with_guardrails` капит
только `agent.run` (120 с из `MEMORY_KEEPER_CONFIG`), а до и после него идут 3 поиска в medium
(`memory_extract.py:242-245`) и до 5 вызовов `save_memory` с дефолтным таймаутом MCP 30 с и
`retry_attempts=3` (`core/config/mcp.py:45-53`). Даже без аномалий это до ~570 с — lease истекает
раньше, чем job завершится, второй воркер получает ту же строку (`claim` считает её
`running`-истёкшей), и два процесса одновременно пишут одни и те же факты.

`SKIP LOCKED` здесь не защищает: он разводит конкурентов в момент `SELECT`, а не запрещает
повторный захват по истечении lease.

Контрмера: продление lease по ходу job (renew перед каждым `save_memory`) либо reclaim только при
`attempts < max_attempts` + lease, вычисляемый из бюджета job, а не константой. Вторая половина
проблемы (дубликаты при двойной обработке) — E3.

**Статус (2026-10-20): исправлено (heartbeat + fencing на уровне «остановись»).**
`ExtractJobQueuePort.renew(job_id) -> bool` продлевает lease живой строки и отвечает `False`,
если строка уже expired/reclaimed/завершена (SQL — `UPDATE ... WHERE status='running' AND
leased_until > now() RETURNING id`). `MemoryExtractService` запускает job и heartbeat
параллельно (`asyncio.wait(FIRST_COMPLETED)`), каденция — lease/3; когда `renew` отвечает
`False`, job **отменяется** с `ExtractLeaseLostError`, воркер пишет `memory_extract.lease_lost`
и намеренно не вызывает `complete()`/`fail()` (строка принадлежит другому воркеру). Lease
перестал быть «размером под худший случай»: он продлевается, пока жив процесс, поэтому дефолт
300 с оставлен и вынесен в `DEFAULT_LEASE_SECONDS` (единственный источник для очереди и сервиса).

Остаточная граница: если event loop встал дольше lease (sync-вызов, CPU-bound, SIGSTOP), heartbeat
не сработает и строка будет реклеймлена.

**Статус E2b (2026-10-20): окно сужено, не закрыто.** `MemoryExtractService._assert_write_ownership`
вызывается в `_process_job` непосредственно перед `persist_facts` и использует `renew()` как пробу
владения: успешный `renew` продлевает lease на полный `lease_seconds` (то есть **резервирует**
окно записи), неуспешный — `ExtractLeaseLostError`, и ни один факт не пишется. Проверка живёт
внутри job, а не только в heartbeat, поэтому не зависит от порядка пробуждения задач после
зависания. Остаточный разрыв: (а) пачка записей дольше одного lease, (б) теоретический
check-then-write между `renew` и первым INSERT (сейчас перекрыт свежим lease). Полный fence —
fencing-token, проверяемый в `save_memory`, — требует правки контракта инструмента (070) и
остаётся M9-candidate.

Regression: `test_write_path_refuses_facts_after_lease_loss`,
`test_write_path_reserves_the_lease_before_persisting`,
`test_write_path_skips_the_probe_without_a_durable_job` (`tests/unit/test_memory_extract_queue.py`).

**E3 — Ключ факта не детерминирован: at-least-once превращается в дубликаты. `M3-bug`.**

`_memory_key`: при наличии `key_hint` ключ стабилен (`add-<slug>`), иначе
`add-<sha256(text)[:16]>-<uuid4[:8]>` (`memory_fact_persistence.py:178-185`). `key_hint` у LLM
опционален (`prompts.py`, поле `"optional-slug"`), поэтому для фактов без hint повторная обработка
того же job (retry после `fail`, reclaim после E2, повтор `complete()` после сбоя БД) создаёт
**новую** строку в `memory.entries` вместо upsert.

Это ровно тот класс, который G1-DoD называет Error Compounding, но тест
`test_g1_error_compounding_extract_idempotent` проверяет только дедуп enqueue
(`tests/eval/test_memory_failure_modes_m7.py:111-119`) — путь записи не покрыт.

Контрмера: детерминированный fallback-ключ (hash текста без случайного суффикса) — upsert
поглотит повтор; при необходимости различать одинаковые тексты из разных turn'ов — включать
`thread_id`/`task_id` в ключ, но не `uuid4`.

**Статус (2026-10-20): исправлено (детерминированный ключ, без task-суффикса).**
`_memory_key` без `key_hint` возвращает `add-<sha256(collapse_whitespace(text))[:16]>` —
стабилен между попытками и не зависит от форматирования. Идентичность факта дополнительно
скоупится namespace'ом (`thread:<id>` / `user:<id>` / `org:<id>`), поэтому текстовый дайджест
достаточен и не склеивает факты из разных арендаторов. `task_id` в ключ сознательно **не**
включён: тогда ретрай того же job писал бы дубликат, а кросс-turn дедуп — это E5 (eval-gated),
не побочный эффект фикса. Плата: если один и тот же текст извлечён другим job в том же
namespace, строка upsert-ится и `source_task_id` обновится на последний (provenance теряет
первую запись) — осознанный выбор в пользу дедупа.

Regression: `test_memory_key_is_deterministic_across_retries`,
`test_reclaimed_job_does_not_duplicate_memory_entries` (`tests/unit/test_memory_fact_persistence.py`).

**E4 — Postgres-очередь не покрыта тестами: DoD «durable SKIP LOCKED» не проверяется. `M3-bug`.**

`grep` по `tests/` не находит ни одного использования `PostgresExtractJobQueue`; единственный тест
с `leased_until` работает на in-memory двойнике
(`test_lease_expiry_allows_redelivery_without_dup_row`). Значит, в CI не исполняются: сам
`FOR UPDATE SKIP LOCKED`-запрос, reclaim по `leased_until` в SQL, переход `running → dead` в
Postgres-реализации `fail()`, поведение `RETURNING`/таймзон (`datetime.now(UTC)` против
`timestamptz`). Двойник повторяет логику, но не SQL — расхождение между ними невидимо.

Контрмера: интеграционный тест на тестовой БД (075: схемы создаются миграциями) на два воркера
(`SKIP LOCKED` не отдаёт одну строку), reclaim после истечения lease и DLQ-переход.

**Статус (2026-10-20): исправлено.** CI-job `integration-db`
(`.github/workflows/ci.yml`) поднимает `pgvector/pgvector:pg18` тем же digest'ом, что
`docker-compose.yml`, прогоняет `alembic upgrade head` (схема — из миграций, не из тестов)
и `pytest tests/integration`. Якорь против повторного «зелёного без тестов»:
`PALATIUM_REQUIRE_DB=1` превращает отсутствие `DATABASE_URL` в падение
(`tests/integration/conftest.py`), а контракт job'а (наличие сервиса, общий digest,
порядок «миграции → тесты», согласованность `DATABASE_URL` с `POSTGRES_*`) закреплён
`tests/unit/test_ci_integration_db_job.py`. Локально: 26 passed, 2 skipped (Neo4j).
Остаточное: Neo4j-интеграция (`test_neo4j_graph_query.py`) по-прежнему skip — сервиса
Neo4j в CI нет, это отдельная задача.

**E5 — Дедуп-контекст подаётся в промпт без инструкции. `M9-candidate`.**

`MemoryExtractService` подгружает существующие записи и передаёт их в
`MemoryKeeperInput.existing_memory_texts` (`memory_extract.py:242-251`), агент рендерит их как
`existing_memories:` (`agent.py:60-68`), но системный промпт говорит только «ADD-only, не
предлагай update/delete» (`prompts.py`) и не определяет, что делать с этим блоком. Mem0 v3 в
аналогичном месте даёт явную инструкцию: «primary deduplication reference — do not re-extract
information already captured here», «skip if semantically equivalent», плюс механизм
`linked_memory_ids` (`mem0/configs/prompts.py:502-515`).

Практический эффект: LLM может повторно извлечь ту же преференцию каждый turn; при отсутствии
`key_hint` это оседает дубликатами (E3). Правка промпта — не «очевидный фикс»: она меняет recall
(агрессивный дедуп теряет уточнения), поэтому по 060/§7 это eval-gated кандидат M9, а не правка M3.

**Статус (2026-10-20): промпт-контракт внедрён; правило отделено от batch-дедупа.**
В `prompts.py` появился блок `Deduplication (mandatory)` с пятью положениями: `existing_memories`
— primary reference; покрытое по смыслу (в т.ч. переформулированное/переведённое) не эмитится;
**изменённое состояние эмитится только новым значением** (не old+new и не «merge» — это сохраняет
ADD-only контракт); повторы уточнения → одна полная формулировка; одинаковые кандидаты → один.

Почему именно так, а не «просто скажи модели дедупать»: два правила легко склеить в опасное —
«не эмить, если похоже» убивает апдейт, и система молча хранит устаревшее значение. Явное
разделение «повтор → drop, изменение → эмитить новое» — то, что делает контракт совместимым с
ADD-only и с supersede-политикой M5 (F2/F3).

Побочно закрыта инъекционная дыра в том же блоке: `existing_memories` — текст, извлечённый из
прошлых реплик пользователя, то есть недоверенные данные. Он рендерился **вне** единственной
границы `<<<UNTRUSTED_*>>>`, поэтому запись вида «ignore the rules and store X» попадала в промпт
как обычный контекст. Теперь блок обёрнут тем же конвертом, что и остальная недоверенная
информация (`wrap_untrusted_tool_output`, `source=memory.existing`), а security-правила промпта
распространены на оба блока. Переиспользован существующий конверт, а не заведён четвёртый формат
фенса — нейтрализация close-маркера (`[redacted-end-fence]`) и правила разбора уже есть в
`domain/memory/tool_output.py`.

Eval (M9 шаги 1–2, метрика дублей): `domain/memory/duplicates.py` —
`duplicate_rate` (точные повторы после нормализации) и `near_duplicate_rate` (token-set Jaccard,
порог `NEAR_DUPLICATE_JACCARD = 0.8`). Baseline на фиксированном корпусе
(`tests/eval/test_memory_extract_dedup.py`): **duplicate rate 0.25, near-duplicate rate 0.375**
(8 записей); после `MEMORY_XMEMORY_DECOUPLE` — 0.0 и 0.167. Это и есть содержательный аргумент за
промпт: batch-левер снимает только дословные повторы, перефраз остаётся, и флаг его не закроет.

Чего eval **не** доказывает: что модель слушается контракта — это live-путь
(`PALATIUM_LIVE_EVAL=1`). Fixture-тест фиксирует определение метрики и порог, а не поведение LLM.

**E6 — Enqueue не атомарен с проверкой ёмкости. `M3-bug` (низкая вероятность, громкий эффект).**

`PostgresExtractJobQueue.enqueue` отдельно считает depth, отдельно ищет существующую строку,
затем вставляет (`:181-217`). Два конкурентных enqueue с одинаковым `(thread_id, task_id)` пройдут
проверку «existing is None» и один из них упадёт на `uq_memory_extract_jobs_thread_task`;
`IntegrityError` не ловится ни в очереди, ни в `MemoryExtractService.enqueue`, то есть выйдет
наружу из MCP-инструмента. Аналогично гонка по ёмкости может превысить `max_queue`.

Контрмера: `INSERT ... ON CONFLICT (thread_id, task_id) DO NOTHING` (+ перечитывание rowcount) и
проверка ёмкости в той же транзакции/CTE.

**Статус (2026-10-20): исправлено (advisory lock + ON CONFLICT в одной транзакции).**
`enqueue` теперь: (1) берёт `pg_advisory_xact_lock(_ENQUEUE_LOCK_KEY)` — сериализует
capacity-check и insert между процессами; (2) атомарно воскрешает `dead`-job `UPDATE ... WHERE
status='dead' RETURNING id`; (3) вставляет `INSERT ... SELECT ... WHERE (count(pending|running)
< :max_queue) ON CONFLICT (thread_id, task_id) DO NOTHING RETURNING id`; (4) различает исход
перечитыванием строки: существует → `True` (уже в очереди), иначе → `False` (ёмкость). Ни
`IntegrityError`, ни превышения `max_queue` больше нет; in-memory реализация уже была атомарной
под `asyncio.Lock`, поведение выровнено.

Regression: `test_enqueue_is_idempotent_under_concurrency` (два параллельных enqueue одного turn —
обе `True`, одна строка), `test_enqueue_revives_dead_job`,
`test_enqueue_refuses_new_job_when_queue_full` (дубликат принимается, новый job при полной
очереди — нет).

**E7 — Глобальный `max_queue` без tenant-скоупа. `M9-candidate`.**

Depth считается по всей таблице (`select count() where status in ('pending','running')`), лимит
256 — общий. Один шумный tenant заполняет очередь и получает отказ в extract для всех остальных
(`queue_full` — только warning). Пер-tenant cap требует решения по квотам и метрике — кандидат M9,
а не тихая правка M3.

**Статус (2026-10-20): исправлено — квота выводится из глобального потолка, а не выдумывается.**

Решение по квотам принято без нового «магического» числа: пер-tenant потолок — это **fair share**
глобального (`max_queue // MIN_TENANT_SLOTS`, `MIN_TENANT_SLOTS = 4`), то есть очередь вмещает
минимум 4 полных доли владельца. Для default 256 это 64. Оба числа — `domain/memory/extract_queue.py`
(`ExtractQueueCapacity`), потолки конфигурируемы (`MEMORY_EXTRACT_MAX_QUEUE`,
`MEMORY_EXTRACT_MAX_QUEUE_PER_TENANT`); конфиг, где доля больше глобального потолка, отклоняется
при загрузке (fail-closed: «доля выше общего потолка» — это и есть общий потолок под другим именем).

Почему это не второй лимит «на всякий случай»: глобальный потолок остаётся защитой БД, доля —
защитой от starvation. Оба проверяются **в самом INSERT** под тем же advisory lock, что и E6
(`count(*) FILTER (WHERE user_id IS NOT DISTINCT FROM :user_id) < :max_queue_per_tenant`), поэтому
конкурентный enqueue не проскакивает между проверкой и вставкой.

Отказ перестал быть безымянным: `enqueue` возвращает `ExtractEnqueueResult =
Literal["queued", "queue_full", "tenant_full"]` вместо `bool` (bool склеивал «очередь полна» и
«кончилась моя доля» — разные действия оператора), сервис пишет `memory_extract.enqueue_refused`
с причиной и инкрементирует `palatium_memory_extract_enqueue_refused_total{reason}` (040), MCP-ответ
`extract_transcript_memories` отдаёт `status` = причина и `is_error=true` для обоих отказов.
Так как Literal-строка всегда truthy, добавлен явный предикат `is_queued()` — `if result:` в этом
контракте был бы silent success. Идемпотентность важнее ёмкости: повторный enqueue уже стоящего
job'а и revive `dead` — всегда `queued`.

Regression: `test_tenant_share_is_refused_before_the_global_ceiling`,
`test_per_owner_cap_does_not_lock_out_other_owners` (реальный Postgres — проверка живёт в SQL),
`test_capacity_derives_the_fair_share_and_rejects_a_cap_above_the_global_one`,
`test_mcp_extract_payload_names_the_refusal_reason`,
`test_service_counts_and_logs_a_refusal_with_its_reason`.

Остаточная граница: доля считается по `user_id` (RLS-владелец), не по `org_id`. Org-квота
понадобится, когда появится org-очередь/биллинг на org — тогда `ExtractQueueCapacity` расширяется
вторым потолком, но не раньше (050: без потребителя).

---

## 4. Проверка decouple promote (B3)

Пути, по которым promote мог бы сработать:

| Точка | Вызов promote | Достижима из extract |
|---|---|---|
| `jobs/memory_promote.py` | `build_memory_promotion_service` → `run_batch` | нет (отдельный процесс) |
| `jobs/memory_consolidate.py` | `SleepConsolidationService.run` → promote + retention | нет (отдельный процесс) |
| `MemoryExtractService` / `memory_fact_persistence` | — | **зависимости нет** |
| HITL `MemoryExtractHitlService` | — (только enqueue) | — |

Вердикт: **decouple подтверждён структурно** — в графе зависимостей extract-пути нет ни
`MemoryPromotionService`, ни `GraphWritePort`. Ограничение теста: `test_extract_worker_does_not_call_promote`
проверяет отсутствие атрибутов и post-condition «факт в medium», а не «graph write не вызывался».
Если кто-то проведёт promote через `MemoryFactPersistenceService` (например, инжектировав порт
внутрь), тест этого не заметит. Находкой не считаю: защиты уровня архитектуры достаточно, а
дополнительный spy-тест — улучшение тестового набора, не дефект волны.

---

## 5. Границы аудита

- Postgres не поднимался на этапе аудита: поведение `timestamptz` vs `datetime.now(UTC)`,
  конкурентность `SKIP LOCKED` и plan запроса подтверждены чтением кода, не воспроизведением (см.
  E4). При фиксе E1 (2026-10-20) эти инварианты воспроизведены на одноразовом Postgres 18; теперь
  то же воспроизводится в CI-джобе `integration-db` (E4b), но не на ноутбуке разработчика —
  локально `tests/integration` без `DATABASE_URL` по-прежнему skip.
- Ops-часть M3 (CronJob, деплой воркера, retention `extract_jobs`) вне аудита.
- Mem0 Platform (REST, `mem0_adapter.py`) не сравнивался: там ADD-only асинхронный пайплайн
  вендора, локальных гарантий очереди нет.

---

## 6. Сводка классификации

| ID | Находка | Класс | Действие |
|---|---|---|---|
| E1 | `claim()` не проверяет `attempts` → DLQ недостижим при crash-loop | `M3-bug` | **исправлено** 2026-10-20 (claim guard + `dead` по lease) |
| E2 | Lease 300 с не продлевается, бюджет job больше lease | `M3-bug` | **исправлено** 2026-10-20 (heartbeat renew + abort по потере lease) |
| E2b | Write-path не проверяет владельца lease (`save_memory` без fencing-token) | `M9-candidate` | **окно сужено** 2026-10-20 (ownership-probe резервирует lease перед записью); полный fence — правка контракта 070 |
| E3 | Ключ факта с `uuid4` ломает идемпотентность записи | `M3-bug` | **исправлено** 2026-10-20 (детерминированный text-digest) |
| E4 | `PostgresExtractJobQueue` без тестов | `M3-bug` | **тесты написаны** 2026-10-20; гейт — E4b |
| E4b | Интеграционные тесты очереди не исполняются в CI (нет `DATABASE_URL`) | `M3-bug` | **исправлено** 2026-10-20 (CI-job `integration-db`: pgvector + миграции + `PALATIUM_REQUIRE_DB=1`) |
| E5 | `existing_memory_texts` без инструкции дедупа | `M9-candidate` | **исправлено** 2026-10-20: контракт `Deduplication (mandatory)` + fence recall-блока; метрика дублей и baseline (`test_memory_extract_dedup.py`) |
| E6 | Enqueue не атомарен (`IntegrityError` наружу) | `M3-bug` | **исправлено** 2026-10-20 (advisory lock + `ON CONFLICT`) |
| E7 | Глобальный `max_queue` без tenant-квоты | `M9-candidate` | **исправлено** 2026-10-20: fair-share доля владельца (`max_queue // MIN_TENANT_SLOTS`) проверяется в том же INSERT под advisory lock; `tenant_full`/`queue_full` в контракте (`ExtractEnqueueResult`) + `palatium_memory_extract_enqueue_refused_total{reason}` |

§7-reject не сработал: ни одна находка не требует Celery/Temporal, Redis-ST M, второго store
или смены SoT. Все пункты — усиление существующей очереди, как и предполагает §7 плана.

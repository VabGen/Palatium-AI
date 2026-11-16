# M9 — eval-gated advanced (design only, flags OFF)

**Дата:** 2026-10-20
**Статус:** proposed. Ни один флаг не включается этим документом.
**Основание:** `.cursor/plans/memory-max-pro.md` §6 (Wave M8), §7 (rejects), §13 (SB0–SB5);
`docs/audit/m5-verification.md`, `docs/audit/m3-verification.md`.

---

## 1. Проблема

Wave M8 объявляет набор «advanced» возможностей флагами, выключенными по умолчанию
(`core/config/memory.py:82-114`). Само по себе наличие флага ничего не гарантирует: часть
флагов в текущем коде **не имеет наблюдаемого эффекта** или измеряется метрикой, которой в
M7 нет. Включение «потому что код есть» даёт complexity theatre (§7) и риск деградации
recall/латентности без возможности откатиться по числу.

Документ фиксирует, что именно и как измерять, прежде чем флаг можно перевести в `true`.

---

## 2. Scope

- Инвентаризация M8-флагов: точка применения, существующий тест, наличие потребителя эффекта.
- Для каждого флага: гипотеза, целевая метрика M7, порог включения, условие отката, стоимость,
  индустриальный прецедент.
- Блокеры, без которых eval невозможен (отдельные волны/PR, не часть M9).

### Вне scope

- Включение флагов, правки кода M5/M3, миграции, новые MCP-инструменты.
- Изменение ADR 0002/0003/0004 и §7 rejects.
- Бенчмарки сторонних продуктов как порог (061: цифры из README не SLO).

---

## 3. Инвентаризация

| Флаг | Default | Точка применения | Тест | Наблюдаемый эффект сегодня |
|---|---|---|---|---|
| `MEMORY_IMPORTANCE_HALF_LIFE_DAYS` | `7.0` — **всегда активен** | `wiring.py:285`, `bootstrap.py:202` → `scoring.rank_by_search_importance` | `tests/unit/test_memory_scoring.py`, `tests/unit/test_memory_advanced_m8.py:38-41` | да: τ-decay в ранжировании |
| `MEMORY_EMBEDDING_RERANK` | `False` | `bootstrap.py:209-219` → `EmbeddingRerankMemoryPort` | `test_memory_advanced_m8` (косвенно) | да: переупорядочивание по эмбеддингам |
| `MEMORY_CROSS_ENCODER_RERANK` | `False` | `bootstrap.py:221-226` | `test_cross_encoder_rerank_reorders` | да, но через **`TokenOverlapCrossEncoder`** — лексический stub |
| `MEMORY_BINARY_QUANTIZE_RERANK` | **ручка удалена** | — (helpers `domain/memory/binary_quantize.py` остались) | `test_binary_quantize_hamming_ranks_similar_vectors_first` | нет: `bit(4096)`-колонки и Hamming-префильтра не подключено, флаг был log-only → снят по §9.2 |
| `MEMORY_BAYESIAN_TRUST` | `False` | `memory_promotion.py:79-80` (`BetaTrust.from_confidence(...).observe_success().mean()`) | `test_bayesian_trust_updates` | да, но **односторонне**: `observe_failure` в прод-коде не вызывается |
| `MEMORY_XMEMORY_DECOUPLE` | `True` — **включён по гейту §5.5** | `memory_promotion.py:66-67` → `decouple_before_aggregate` | `test_memory_advanced_m8`, `test_m9_flag_gates` | да: число промоутов на батч; duplicate rate 0.25 → 0.0 без потери фактов |
| `MEMORY_HEBBIAN_EDGE_BUMP` | **ручка удалена** | — (порт `bump_hebbian_on_entry` остался без вызывающего) | `test_hebbian_bump_asymptotic`, `test_eval_reinforcement_lift_is_zero_*` | **нет в Select** → флаг снят по §9.2; `hebbian_weight` по-прежнему не участвует в ранжировании |
| `emotional_valence` | поле payload, не флаг | `memory_tool_ops.py:213-228` | — | да: хранится, на Select не влияет |

Расхождение с планом: §6 M8 утверждает «All flags **OFF** by default», но
`MEMORY_IMPORTANCE_HALF_LIFE_DAYS` — не переключатель, а значение с дефолтом `7.0`, и τ-decay
работает всегда. Формулировку в плане стоит уточнить (значение vs флаг), чтобы «OFF by default»
не читалось как «τ-decay выключен».

---

## 4. Что M7 сегодня измеряет, а что нет

Есть:

- `palatium_memory_recall_at_k` (`metrics.py:129`) + `tests/eval/test_memory_failure_modes_m7.py`
  (`test_m7_recall_at_k_above_slo`, порог Recall@4 ≥ 0.85 на фиксированном корпусе);
- five failure modes G1 (`forget→expire`, budget clip, silent death, extract idempotent,
  queue cap);
- faithfulness / context precision как чистые функции (`test_g7_faithfulness_and_precision_pure`);
- promote-эвал (порог важности, частота, идемпотентность повторного батча).

Нет метрики, на которую могли бы опереться четыре флага из семи:

| Метрика, которой нет | Зачем нужна | Какой флаг без неё не проверить |
|---|---|---|
| **Supersede precision** (доля корректно вытесненных фактов на корпусе противоречий) — *сделано 2026-10-20:* `supersede_precision` / `supersede_recall` + корпус (`tests/eval/test_m9_eval_metrics.py`) | Ловит и «не вытеснил», и «вытеснил лишнее» | Bayesian α/β, xMemory decouple |
| **Duplicate rate в L4** (доля активных фактов с одинаковым смыслом) — *сделано 2026-10-20:* `domain/memory/duplicates.py` (`duplicate_rate` / `near_duplicate_rate`) | Цена отсутствия дедупа | xMemory decouple |
| **Context precision@k после реранка** (доля релевантных в топ-k) — *сделано 2026-10-20:* `test_eval_context_precision_at_k_improves_after_rerank` (0.5 → 1.0) | Реранк меняет порядок, не Recall@k | Cross-encoder, embedding rerank |
| **Query p95** (уже есть `palatium_memory_query_duration_seconds`, но эвал его не проверяет) — *сделано 2026-10-20:* `tests/perf/test_memory_query_latency.py` (реальный pgvector, маркер `slow`): бюджет SLO + инвариант числа SELECT-ов | Стоимость реранка | Binary quantize, cross-encoder |
| **Reinforcement lift** (растёт ли вероятность выбрать факт после повторного подтверждения) — *сделано 2026-10-20:* `reinforcement_lift`, замер = **0.0** (потребителя в ранжировании нет) | Единственный смысл Hebbian-веса | Hebbian edge bump |

Без этих пяти метрик «eval-gated» превращается в «включили и смотрим на прод» — то, что §7
запрещает.

---

## 5. Дизайн по флагам

### 5.1 `MEMORY_IMPORTANCE_HALF_LIFE_DAYS` (уже активен, 7.0)

- **Гипотеза:** half-life, соответствующий реальному горизонту актуальности преференций
  (дни, не часы), повышает Recall@4 на корпусе с «устаревшими» и «свежими» формулировками
  одного предпочтения.
- **Метрика:** Recall@4 (M7) + доля stale-побед (устаревший факт выше свежего).
- **Порог включения/изменения:** только как A/B по значениям `{3, 7, 30, 90}` при
  неизменном корпусе; принимается значение с максимальным Recall@4 при stale-побед ≤ текущего.
- **Откат:** значение возвращается к `7.0` (не код, только env).
- **Стоимость:** ноль latency, влияет на ранжирование.
- **Прецедент:** τ-decay как search-time фактор (060.2); точное значение — только по своему корпусу.

### 5.2 `MEMORY_EMBEDDING_RERANK`

- **Гипотеза:** повторное кодирование пары «запрос-кандидат» поднимает context precision@3
  на запросах с перефразированием (синонимы, другой язык).
- **Метрика:** context precision@3 (новая) + Recall@4 не ниже baseline − tolerance.
- **Порог:** context precision ≥ baseline + 0.05 при Recall@4 −0.02…0; p95 ≤ baseline × 1.5.
- **Откат:** флаг `false` (поведение порта без обёртки).
- **Стоимость:** один embedding-вызов на запрос (+ overfetch), деньги/латентность.
- **Прецедент:** двухстадийный retrieve→rerank (индустриальный стандарт RAG); в проекте —
  `infrastructure/memory/embedding_rerank.py`.

### 5.3 `MEMORY_CROSS_ENCODER_RERANK`

- **Блокер:** в проде подключается `TokenOverlapCrossEncoder` (`stub_cross_encoder.py`) —
  доля совпавших токенов. Это не cross-encoder: он измеряет лексику, которую уже даёт FTS,
  поэтому текущий флаг **нельзя** eval-гейтить в его нынешнем виде.
- **Гипотеза (после реального CE):** semantic rerank поднимает precision@3 на запросах,
  где лексического пересечения нет.
- **Метрика:** context precision@3 + p95.
- **Порог:** precision +0.08, Recall@4 не ниже, p95 × 2 не выше.
- **Откат:** `false`.
- **Прецедент:** cross-encoder rerank как вторая стадия (Zep/Graphiti строят поиск иначе —
  у них граф + BM25/cosine, CE нет; прецедент общий RAG, а не конкретный репозиторий).

### 5.4 `MEMORY_BINARY_QUANTIZE_RERANK` — ручка удалена 2026-10-20

- **Статус:** флаг снят из `MemoryConfig`/env/bootstrap как no-op (§9.2, 050: нет неиспользуемых
  ручек). `domain/memory/binary_quantize.py` и его тесты остались — это чистая функция, которая
  понадобится волне `bit(4096)`.
- **Блокер:** нет `bit(4096)`-колонки и Hamming-префильтра. Eval невозможен до миграции —
  отдельная волна с reindex (060). Возврат ручки = сначала миграция, затем гейт в
  `test_m9_flag_gates.py` (тест `test_gate_pruned_knobs_stay_removed` не даст вернуть её молча).
- **Гипотеза (после миграции):** Hamming-префильтр снижает p95 на 4096-мерном exact-cosine
  без падения Recall@4.
- **Метрика:** p95 + Recall@4.
- **Порог:** p95 −30%, Recall@4 −0.01…0.
- **Откат:** exact cosine (после удаления ручки — отсутствие ветки в bootstrap).
- **Прецедент:** binary quantization + rerank (060 уже фиксирует этот путь как опциональный).

### 5.5 `MEMORY_XMEMORY_DECOUPLE`

- **Статус 2026-10-20: ON (step 3).** Гейт `tests/eval/test_m9_flag_gates.py` прогоняет
  реальный `MemoryPromotionService.run_batch` на корпусе `RAW_EXTRACT`: duplicate rate
  **0.25 → 0.0** (−100% при пороге −50%), near-duplicate 0.375 → 0.167, набор
  нормализованных фактов после promote **идентичен** (Recall-прокси не падает). Откат —
  `MEMORY_XMEMORY_DECOUPLE=false`, код не меняется.
- **Гипотеза:** near-dup collapse в promote-батче снижает duplicate rate в L4 без потери
  Recall@4 (дубликаты не несут новой информации).
- **Метрика:** duplicate rate в L4 (новая) + Recall@4 + число промоутов на батч.
- **Порог:** duplicate rate −50% относительно baseline, Recall@4 −0.01…0.
- **Откат:** `false`.
- **Стоимость:** ноль на hot-path (batch job).
- **Прецедент:** dedupe-before-aggregate в sleep-time пайплайнах (Mem0: «primary deduplication
  reference» перед извлечением); в проекте — `domain/memory/xmemory.py`.

### 5.6 `MEMORY_BAYESIAN_TRUST`

- **Блокер дизайна:** в коде вызывается только `observe_success()`
  (`memory_promotion.py:80`), `observe_failure()` не вызывается нигде. Значит, α растёт, β
  постоянна, и confidence монотонно стремится к 1.0 при каждом повторном promote того же
  факта — независимо от того, был он вытеснен или нет. Флаг в таком виде измеряет не доверие,
  а число повторных промоутов.
- **Предусловие:** подключить `observe_failure` на путь `supersede` (и на `blocked_pii`-отказ),
  иначе eval бессмыслен. Это отдельный PR, а не «включение флага».
- **Гипотеза (после):** Beta-Bernoulli confidence повышает supersede precision — вытесняется
  то, что действительно противоречит, а не случайное уточнение.
- **Метрика:** supersede precision (новая) + Recall@4.
- **Порог:** precision +0.05, Recall@4 −0.01…0.
- **Откат:** `false` (скалярный `confidence` из MemoryKeeper, как сейчас).
- **Прецедент:** Beta-Bernoulli как trust-модель факта; в Graphiti аналога нет — там
  инвалидация решается датами, не вероятностью (это и есть причина не тянуть Graphiti как SoT).

### 5.7 `MEMORY_HEBBIAN_EDGE_BUMP` — ручка удалена 2026-10-20

- **Статус:** флаг снят из `MemoryConfig`/env и из `MemoryPromotionService` (§9.2, 050: нет
  неиспользуемых ручек). `domain/memory/hebbian.py` и порт `bump_hebbian_on_entry` остались
  как capability — у них нет вызывающего, пока у веса нет потребителя в Select.
- **Блокер:** `hebbian_weight` пишется (`bump_hebbian_on_entry`) и читается только для
  следующего бампа (`_FIND_ACTIVE_CYPHER` возвращает вес, `_SET_HEBBIAN` пишет). В Select он
  не участвует: `rank_by_search_importance` использует recency/relevance/access_frequency.
  Эффекта на ответ нет — eval-гейтить нечего; измеренный reinforcement lift = **0.0**.
- **Предусловие:** решение о потребителе (например, слагаемое в search-time importance),
  что само по себе меняет формулу 060.2 и требует eval-дизайна до кода.
- **Гипотеза (после):** усиление часто подтверждаемых фактов повышает их долю в топ-k.
- **Метрика:** reinforcement lift (новая) + Recall@4 + stale-побед не больше baseline.
- **Порог:** lift ≥ 0.05 при Recall@4 −0.01…0.
- **Откат:** отсутствует ветка в promote (после удаления ручки откатывать нечего).
- **Прецедент:** Hebbian reinforcement как эвристика; в Letta аналог — eviction priority,
  не вес ребра.

### 5.8 `emotional_valence`

- **Статус:** поле payload, не флаг; на Select не влияет.
- **Что нужно, чтобы стало предметом M9:** сначала потребитель (ранжирование/фильтр) —
  иначе это метаданные, а не поведение. До этого eval-критерий не формулируется.

---

## 6. Порядок работ (предложение, не выполнение)

| Шаг | Содержание | Тип |
|---|---|---|
| 1 | Добавить недостающие метрики: supersede precision, duplicate rate, context precision@k, reinforcement lift — как offline-эвалы на фиксированном корпусе; query p95 — на живом pgvector (`tests/perf/`, `slow`) | PR (eval) |
| 2 | Зафиксировать baseline этих метрик при всех флагах `false` | PR (eval) |
| 3 | `MEMORY_XMEMORY_DECOUPLE`, `MEMORY_EMBEDDING_RERANK` — первыми: есть потребитель, эффект наблюдаем | PR (flag) |
| 4 | `MEMORY_BAYESIAN_TRUST` — только после подключения `observe_failure` на supersede | PR (код) + PR (flag) |
| 5 | `MEMORY_CROSS_ENCODER_RERANK` — после реального `CrossEncoderPort` | PR (код) + PR (flag) |
| 6 | `MEMORY_HEBBIAN_EDGE_BUMP` — **ручка снята** (§9.2); вернуть только вместе с потребителем в ранжировании | design → код → гейт → флаг |
| 7 | `MEMORY_BINARY_QUANTIZE_RERANK` — **ручка снята** (§9.2); вернуть после миграции `bit(4096)` + reindex | миграция → гейт → флаг |

Каждый шаг 3–7 — отдельный PR с числами «до/после» в описании и ссылкой на этот документ.

**Статус шага 3 (2026-10-20).**

- `MEMORY_XMEMORY_DECOUPLE` — **включён** (`default=True`, env `*.example` = `true`):
  duplicate rate **0.25 → 0.0**, near-duplicate 0.375 → 0.167, множество промоутнутых фактов
  не изменилось. Гейт — `tests/eval/test_m9_flag_gates.py::test_gate_xmemory_decouple_*`
  (реальный `MemoryPromotionService`, не helper в вакууме). Откат — один env-ключ.
- `MEMORY_EMBEDDING_RERANK` — **остаётся OFF.** Precision-часть гейта зелёная
  (0.5 → 1.0, `test_eval_context_precision_at_k_improves_after_rerank`), но порог §5.2
  требует ещё `p95 ≤ baseline × 1.5` **с живым embedding-gateway**; локальный замер с
  детерминированными эмбеддингами измеряет pgvector, а не провайдера, поэтому доказательства
  нет. Гейт зафиксирован в `test_m9_flag_gates.py::test_gate_blocked_flags_stay_off` —
  включение без этого замера роняет тест.

**Статус шагов 1–2 (2026-10-20).** Baseline зафиксирован при всех флагах `false`, все пять
метрик — на реальном коде/кластере, не на моках:

- **duplicate rate** (`tests/eval/test_memory_extract_dedup.py`): корпус 8 «сырых» извлечений —
  **0.25** exact / **0.375** near (Jaccard 0.8); после batch-collapse (`MEMORY_XMEMORY_DECOUPLE`)
  — **0.0 / 0.167**.
- **supersede precision / recall** (`tests/eval/test_m9_eval_metrics.py`): корпус 4 кандидатов,
  2 противоречия (одно PII) — **precision 1.0**, **recall 0.5**. Recall 0.5 — это измеренный долг
  F3 (PII-флип ждёт человека), а не сбой: метрика специально считает исход, не намерение.
- **context precision@k после реранка**: token-stuffed дистрактор выигрывает лексический проход
  (top-2 = `b`,`d`, precision **0.5**), `EmbeddingRerankMemoryPort` возвращает `b`,`c` (**1.0**),
  Recall@2 не падает. Эмбеддинги — детерминированный стенд (провайдер в CI не зовётся), поэтому
  это проверка механики реранка, а не качества модели.
- **reinforcement lift** (`test_eval_reinforcement_lift_is_zero_because_no_ranker_reads_the_weight`):
  вес растёт (0 → 0.1 → 0.19), но `list_active_facts` сортирует по importance/confidence —
  **lift ровно 0.0**. Это и есть гейт §6 шага 6: включать `MEMORY_HEBBIAN_EDGE_BUMP` сейчас
  бессмысленно, он меняет только хранимое состояние. Когда появится потребитель, 0.0 обязано
  измениться осознанно.
- **query p95** (`tests/perf/test_memory_query_latency.py`, `-m slow`, реальный pgvector):
  корпус 400 фактов на пользователя, `limit=8`, 25 замеров после прогрева —
  **p95 117.5 мс / p50 98.4 мс** на Windows + Docker Desktop. Для сравнения: голый
  pgvector-план (400 строк × 4096, тот же контейнер) — **6.7 мс**, то есть стоимость сидит не в
  самой косинусной дистанции, а вокруг неё (чтение/детоаст строк по 16 КБ и клиентская
  сериализация 4096-мерного вектора); по частям не профилировалось. Бюджет гейта — SLO 060
  (**200 мс**), поэтому красный прогон означает «SLO не выполняется здесь» либо регрессию,
  а не «раннер был занят».
  Второй, детерминированный гейт — число `SELECT` на запрос: **4** (RLS `set_config` на
  сессию × 2 + FTS + exact cosine) и **одинаковое на 100 и 400 строках** — это N+1-детектор,
  который не зависит от машины. Запуск — job `memory-query-latency` (perf-nightly, свой
  pgvector + `alembic upgrade head` + `PALATIUM_REQUIRE_DB=1`).
  Этот же замер — baseline для §5.4: vector-проход доминирует над FTS, значит `bit(4096)` +
  Hamming-префильтр целятся именно в него, а не в гибридную сборку.

Побочный вывод для шага 3: batch-левер закрывает только дословные повторы, перефраз остаётся —
значит `MEMORY_XMEMORY_DECOUPLE` сам по себе не может быть «дедупом», и его порог (−50% duplicate
rate) надо считать по `duplicate_rate`, а не по near-rate. Перефраз — зона промпта (E5,
M3-audit): контракт `Deduplication (mandatory)` внедрён там же.

Измеренный побочный факт, не ставший продуктовым решением: гибридный `search` открывает две
RLS-сессии (FTS и vector раздельно), поэтому делает два `set_config`-roundtrip'а там, где хватило
бы одного. Гейт зафиксирован как «не больше 4 SELECT» (улучшение до 3 пройдёт, рост — нет).

---

## 7. DoD

- Для каждого флага в §3 есть: метрика, порог, условие отката, стоимость.
- Baseline зафиксирован при `false`; включение любого флага сопровождается парой чисел.
- Блокеры §5.3–5.7 либо закрыты, либо флаг остаётся `false` с явной пометкой в плане.
- Ни один флаг не включён этим документом.

## 8. Enforcement

| Гейт | Где | Что роняет |
|---|---|---|
| Baseline не ухудшен | `tests/eval/`, сравнение с `baseline − tolerance` (075) | PR с включённым флагом без чисел |
| Флаг ↔ гейт | `tests/eval/test_m9_flag_gates.py` | включение заблокированного флага (default `True` без закрытого блокера), возврат снятой ручки, выключение гейтованного без чисел |
| Порог из §5 | описание PR | включение «по ощущению» |
| Флаг без потребителя (Hebbian, binary quantize) | `test_gate_pruned_knobs_stay_removed` + ревью | возврат no-op флага |
| `MEMORY_BACKEND`/`GRAPH_QUERY_BACKEND` не меняются | bootstrap fail-closed | попытка включить чужой backend как «оптимизацию» |

## 9. Открытые вопросы

1. Достаточен ли существующий корпус M7 для supersede precision, или нужен отдельный
   contradiction-корпус (пары «A → не-A» с эталонной меткой)? Предложение: отдельный
   фикстурный корпус в `tests/eval/fixtures/`, потому что Recall@k его не заменяет.
2. ~~Reinforcement lift требует, чтобы вес влиял на порядок~~ — **решено 2026-10-20:** ручка
   `MEMORY_HEBBIAN_EDGE_BUMP` удалена как мёртвая (050), доменный хелпер и порт остались.
   Возврат флага возможен только вместе с потребителем в ранжировании и гейтом в
   `test_m9_flag_gates.py`.
3. `emotional_valence`: продуктовое решение (нужен ли эмоциональный вес в ранжировании)
   до любого eval — иначе поле останется метаданными.

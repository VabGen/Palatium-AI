# Latency: один writer на turn (устранение двойной генерации)

Дополняет `.cursor/plans/structured-streaming.md` (формат кадров) и
`evolution-to-big-tech.md` (Phase 1 Hybrid SSE — уже в коде). Здесь — только
latency-разрыв: **на каждый turn два разных LLM последовательно пишут один и тот же
ответ целиком**. Дублей с 000/030/040/055/065 не создаём (050).

## 1. Измерение (trace `cd0f2fed`)

| Узел | Время | Выход | Эффективный темп |
|---|---|---|---|
| `researcher` (`reason_only`) | 16 625 ms | `summary` ≈ 3–4 k chars | ~85 tok/s |
| `critic` | 85 ms | passthrough (без LLM) | — |
| `formatter` (`schema_first`) | 22 878 ms | `ContentDocument` 6 018 chars | ~110 tok/s |

Оба узла — `model_tier="small"` (`formatter/config.py:15`,
`domain/policies/researcher_tier.py` для `reason_only`). Значит 39.5 s — это не
«медленная модель», а **два полных прохода генерации**: сначала worker пишет
готовый ответ (`researcher/prompts.py` — «summary is the user-facing answer»), затем
Formatter переписывает его в документ.

Ключевая метрика — **`structure_divergence`** (не `len(formatter)/len(researcher)` и не
Levenshtein, см. §3.4): доля блоков финального документа, у которых нет источника в
worker-ответе, плюс доля фактов, появившихся только во втором проходе. Для
`cd0f2fed` — ≈0 по фактам (весь смысл пришёл из worker'а), но 100 % блоков новые,
потому что Formatter — второй writer. Пока `structure_divergence > 0.3`, любая
оптимизация TTFT лечит симптом.

## 2. Почему два предложенных варианта не решают

### 2.1 Tiering — не рычаг

- Formatter уже `small`; researcher на `reason_only` тоже `small`. «Перевести
  formatter на mid для длинных» = **замедлить** его (mid — сильнее и дороже).
- `max_tokens` не влияет на скорость потокенной генерации, только на потолок
  (обрезка). Уменьшать его = резать ответ.
- Остаётся `nano` для formatter: −10…20 % на 23 s, при риске потерять структуру.
  Как отдельный FinOps-шаг — да; как ответ на 40 s — нет.

### 2.2 Параллельный старт Formatter'а на первом токене researcher'а — антипаттерн здесь

Переписывание не является причинно-устойчивым к префиксу: секции, порядок, таблица
сравнения и вывод зависят от **всего** источника. Формаatter, стартовавший на
первом токене, обязан переписать уже показанное, когда придёт хвост — это ровно тот
`replace`, который убрал `structured_incremental`, плюс двойная оплата. Финал всё
равно ждёт последнего токена researcher'а.

Единственная легальная форма параллелизма — **causal section streaming**: researcher
закрывает секцию → formatter форматирует только её → кадр append-only, `section_id`,
никаких переписываний. Но это по-прежнему **вторая генерация** (+15…25 % токенов), а
total ≈ `formatter(total)` ≈ 23 s при TTFV ≈ 5 s. Single-writer даёт ≈ 17 s total и
TTFV ≈ 2 s — доминирует по обеим осям. Поэтому section streaming не берём.

## 3. Целевой контракт: ровно один writer на turn
Ось — в `domain/policies/types.py` (010/055), решение — чистая политика:

```python
PresentationOwner = Literal["worker", "formatter"]

class PresentationOwnershipPolicy:
    def decide(
        self,
        *,
        task_kind: TaskKind,
        continuation_kind: ContinuationKind | None,
        transformation: TransformationKind,
        requires_user_choice: bool,
        underspecification: UnderspecificationKind,
        style_hint: FormatterStyleHint | None,
    ) -> PresentationOwner: ...
```

`worker` (Researcher пишет финальный GFM, Formatter — детерминированный рендер):

- `knowledge_request` / `tool_execution` / `multi_step_workflow` без
  `restructure`, без `requires_user_choice`, `underspecification == "none"`,
  `style_hint ∉ {brand_sections_icons, restructure_sections_icons, choice_cards}`;
  locale совпадает, worker confident, `requires_review == False`.

`formatter` (Formatter — единственный writer): `format_only` /
`response_formatting`, clarify/choice, brand/restructure, verbatim, locale mismatch,
revision, любой случай, где worker-ответ не является готовым текстом.

Правило без эвристик по формулировке (055): владелец выбирается по осям плана, а не
по «похоже на markdown».

### 3.1 Рабочий путь

1. Researcher отдаёт `summary` **потоком** (сейчас `call_llm`, `json_object`,
   `llm_research.py:94`). Порядок ключей провайдером не гарантирован, поэтому не
   «JSON начинается с summary», а сканер ищет ключ `"summary"` на глубине 1 и
   стримит только его строковое значение:
   - стримим `call_llm_stream(response_format="json_object")`;
   - новый `PartialJsonString` (рядом с `partial_document.py`) декодирует **только**
     значение `summary`, удерживая хвост незавершённого escape/`\uXXXX`; до
     появления ключа кадров нет (тишина — не ошибка);
   - кадры — через общий prose-emitter (§3.3), `replace` не выставляется.
   Контракт `parse_researcher_output` / `confidence` / `sources_used` не меняется:
   финальный `summary` всё равно проходит через `parse_researcher_output` и
   `SUMMARY_MAX_CHARS`, поэтому preview может быть на несколько символов длиннее
   финала — это надмножество, не расхождение.
2. Formatter при `owner == worker`:
   - `markdown_to_content_document(worker_summary, task_input)` +
     `align_formatter_meta` — детерминированно, без LLM;
   - fallback на существующий LLM-путь, если парсер дал 0 блоков / сработал
     truncation-маркер / locale mismatch (fail-open по качеству, не по тишине);
   - метрика `formatter_path=deterministic_gfm`.
3. При `owner == formatter` researcher **не** пишет финальный текст (для
   `format_only` он и так пропускается, `supervisor/routing.py:26`), а для
   brand/restructure его `summary` остаётся источником — как сейчас.

### 3.2 Revision

Critic может вернуть `requires_review` → researcher перегенерирует с feedback. Это
**новый контент**, а не перерисовка: `TurnSseBridge` получает `revision_epoch`,
разрешает один `replace` на эпоху и пишет
`palatium_sse_layout_shift_total{contract="revision"}`. Инвариант «не перекрашивать
тот же текст» сохраняется.

### 3.3 Общий prose-emitter

`FormatterMarkdownEmitter` (`formatter/stream_delta.py`) уже делает нужное:
санитизация внутренних терминов, hold-back незакрытого `<icon>`/emoji, `text_delta`
+ dual `answer_delta`, TTFT-метрика. Вынести его в
`application/services/prose_stream.py` (класс `ProseStreamEmitter`), форматтер и
researcher используют один экземпляр контракта. Не копировать (050).

### 3.4 Critic и HITL — что реально требуется (проверено по коду)

Порядок узлов (`application/orchestration/graph.py:90-96`):
`researcher|coder|analyst|parallel → critic → formatter → END`. То есть **critic уже
стоит до formatter'а** и уже получает `worker_summary`, а не финальный документ
(`build_critic_input`). При `writer=worker` его вход не меняется вообще — он и так
судит текст, который станет ответом. Требование «переподчинить critic» снимается:
работы 0.

`hitl.interaction_plan` живёт **после графа** (`intent_hitl_flow.finalize_*`,
`InteractionAssembler.assemble`), работает по готовому `ContentDocument` и не зависит
от авторства. Детерминированный рендер даёт тот же тип объекта → миграции нет.

`AttachmentReferenceResolver` вызывается только на уже упавшем turn'е
(`execution_error == ATTACHMENT_REFERENCE_UNRESOLVED`, `_mint_file_choice_card`) —
чтобы превратить отказ в карточку файлов. Он не является pre-writer шагом и не
должен туда переезжать.

**Настоящий риск — другой:** `HitlInteractionPolicy._is_menu_shaped` считает
menu-shaped любой ответ, где есть один `ListBlock` + ≤3 фрейм-блока. Проверено на
живом объекте:

```text
heading + paragraph + список из 3 пунктов →
menu_shaped=True, required_choice=True, choices=3, promoted_from=list
```

То есть легитимный ответ «три причины» получает кликабельную choice-карточку
(поведение зафиксировано тестом `test_heading_plus_list_still_menu_shaped`).
Сегодня это редкость, потому что LLM обычно пишет прозу абзацами; детерминированный
рендер **надёжно** делает из `- пункт` `ListBlock`, поэтому при `writer=worker`
частота вырастет. Это не повод менять политику «заодно» (055) — это гейт: измерить
`hitl_choice_cards_minted / turns` на worker-owned маршруте в shadow-режиме
(writer выбирается и логируется, но рендер идёт старый). Решение о политике —
отдельное, с владельцем продукта.

## 4. Pre-P1 checklist (гейт на старт)

### 4.0 Замеренный baseline (2026-10-19)

Источники — локальный compose, read-only, без LLM и embed-вызовов:

- 646 сохранённых `ContentDocument` из экспорта assistant-turn'ов (JSONL-дамп
  `dialog_turns.payload`, `schema=assistant_turn_v1`) — распределение block-типов.
  **Источник не воспроизводим:** дамп удалён как PII, `dialog_turns` локально
  содержит 28 строк. Поэтому callout/list-частоты пересчитаны на парной популяции
  (§4.0.5), а не на экспорте;
- 185–187 терминальных turn'ов из LangGraph checkpointer (`public.checkpoints`), где
  `formatter.task_id == researcher.task_id` — пары «worker draft → финальный
  документ». Пары с разными `task_id` отброшены: каналы state живут в треде и
  протекают из предыдущего turn'а (без этого фильтра замер даёт ложные 100 %
  divergence).

Скрипты: `scripts/measure_structure_fidelity.py`,
`scripts/measure_structure_divergence.py`, `scripts/measure_verbatim_parse.py`,
`scripts/explain_verbatim_failures.py`, `scripts/analyse_recall_tail.py`,
`scripts/measure_writer_enrichment.py`, `scripts/measure_callout_baseline.py`.

Счётчики между прогонами дрейфуют на 1–2 turn'а (живая БД, в т.ч. ретраи одного
хода): 185–187 пар, 100–102 verbatim. Гейты фиксируются на снапшоте со списком
`task_id`, а не на текущем count.

`structure_divergence` на 186 парах:

| metric | mean | p50 | p90 | p95 | max |
|---|---|---|---|---|---|
| `shingle_containment` | 0.812 | 0.960 | 1.000 | 1.000 | 1.000 |
| `block_coverage` | 0.777 | 1.000 | 1.000 | 1.000 | 1.000 |
| `structure_divergence` | 0.188 | 0.036 | 0.802 | 0.975 | 1.000 |

Распределение бимодальное, mean бесполезен как решение:

| bucket | turns | share | mean blocks | mean formatter s |
|---|---|---|---|---|
| 0.00–0.05 (verbatim) | 102 | 54.8 % | 6.2 | 3.5 |
| 0.05–0.20 | 36 | 19.4 % | 8.2 | 7.2 |
| 0.20–0.50 (partial) | 19 | 10.2 % | 8.6 | 7.1 |
| 0.50–0.80 (rewrite) | 9 | 4.8 % | 8.4 | 4.9 |
| 0.80–1.00 (full regen) | 20 | 10.8 % | 7.0 | 4.3 |

Formatter-узел (по `checkpoint.ts`): mean 4.7 s, p50 3.1 s, p90 11.9 s, max 29.6 s.
Researcher-узел: p50 2.8 s, p90 10.6 s, max 17.6 s.

Три вывода, которые меняют план:

1. **Основная потеря — не divergence, а оплаченная копия.** Половина turn'ов
   (54.8 %) выдаёт ≥95 % текста worker'а дословно и всё равно тратит ~3.5 с LLM.
   Детерминированный путь убирает не «переписывание», а *повторную сериализацию*
   уже готового ответа.
2. **Хвост — это не стиль, а корректность.** В 10.8 % (0.80–1.00) `block_coverage=0`:
   финальный документ не содержит ни одного блока из worker'а. Разбор 18 таких
   turn'ов — §4.0.3: worker не был пустым ни разу, formatter не «спас» ни разу.
3. **`block_coverage` информативнее shingle-containment на хвосте.** В полном
   re-generation оба насыщаются (1.00 / 0.00), но containment может остаться
   высокой при добавленных блоках — coverage падает первой. Порог гейта вешать на
   coverage, divergence оставить сигналом.

### 4.0.1 `verbatim_parse_success` (100 verbatim turn'ов)

Ключевой вопрос: на какой доле verbatim-turn'ов детерминированный рендер даёт
**тот же** документ. Если он ниже гейта, `PCT>0` экономит не 54.8 %, а меньше —
остаток уходит в LLM-formatter.

**Две разные метрики, один блокирующий гейт (не смешивать):**

| метрика | определение | роль |
|---|---|---|
| `exact_parse` (**strict**) | совпали и типы, и тексты всех блоков | диагностика, **не** гейт |
| `information_fidelity` (**info**) | `token_recall ≥ 0.99` и документ не пуст | **блокер P1** |

Причина разделения: strict-провал ≠ потеря информации. 21 strict-провал
раскладывается на **15 с потерей текста** и **6 shape-only** (токены те же,
изменилась нарезка: `- **Label**: value` → `kv`, нумерованный список → `steps`,
list разрезан). kv/steps promotion в strict-таблице считался failure'ом дважды:
как shape-изменение и как «потеря». В info-гейте он не failure.

Текущие значения:

| вердикт | доля |
|---|---|
| `exact_parse` (strict) | **79/100 = 79.0 %** |
| `information_fidelity` (info gate) | **85/100 = 85.0 %** |
| конкатенированный текст равен | 81/100 = 81.0 % |
| ни один блок не потерян (substring) | 82/100 = 82.0 % |

Token recall: mean 0.9930, p50 1.000, p90 1.000, **p10 0.9751, min 0.8844**.

**Rerun 2026-10-19** (187 turns, 101 verbatim; parser P1c applied, drafts still
pre-prompt): `exact` 76.2 %, `information_fidelity` (`token_recall ≥ 0.99`) **85.1 %**
(86/101), p10 0.9751, `nested_bullet` 19.3 %, `kv_no_bullet` 3.2 %. This is a
regression baseline, **not** the post-prompt gate: stored drafts predate the
`##`/callout contract, so the ≥ 0.90 info gate is re-measured after fresh dev turns.
Until it passes, `ANSWER_WRITER_MODE` stays `formatter` / `PCT=0`.

**Промпт-фикс — гипотеза, а не «должно поднять выше 80 %».** Ожидаемый диапазон
после `##`-контракта: 79 + 0.7–1.0 × 12 ≈ **88–96 %** strict и **92–96 %** info
(11 из 15 content-loss turn'ов теряют именно заголовки). Поэтому:

- **P1 не стартует**, пока `measure_verbatim_parse.py` не перезапущен после
  правки промпта и не подтвердил `information_fidelity ≥ 0.90` + `p10 ≥ 0.97`;
- если после промпта info = 0.85–0.89 — промпт итеративно чинится **до** P1, а не
  после; если 0.90+ — идём в P1c закрывать остаток (`nested_bullet` + `kv`);
- strict фиксируется как диагностика с ориентиром ≥ 0.80, но `PCT=5` от него не
  зависит: strict-провал при сохранённом тексте — это не UX-регрессия.

Декомпозиция 21 strict-провала (категории пересекаются — один turn может иметь
несколько причин, сумма > 21):

| причина | turn'ов | класс |
|---|---|---|
| потеря `heading` (34 блока) | 12 | **content loss**, лечится промптом (worker не эмитил `##`) |
| `nested_bullet` (плоский list) | 9 | content loss, P1c |
| list разъехался/склеился | 5 | в основном следствие потери заголовков |
| `kv` промотирован из буллетов | 5 | shape-only |
| `steps` промотирован | 3 | shape-only |
| `kv` без буллета | 2 | content loss, P1c |
| `callout` с title в строке маркера | **0** | в worker-драфтах не встречается |
| code fence в list item | **0** | в worker-драфтах не встречается |

Частота конструкций в worker-драфтах (185–187 turn'ов): `nested_bullet` —
**17.7–18.4 %** (33–34 turn'а), `kv_no_bullet` — 3.2 % (6), `callout_with_title` —
0, `fence_in_list` — 0. Это не «<1 %, не расширять»: вложенность в каждом шестом
ответе.

### 4.0.2 Хвост `token_recall < 0.99`: источник (закрыто)

15 из 100 verbatim-turn'ов имеют recall < 0.99. Источник:

| класс | turn'ов | деталь |
|---|---|---|
| теряют `heading` (те же 12) | **11/15** | промпт-фикс; после него recall этих turn'ов → 1.0 |
| независимые парсер-баги | **4/15** | промпт их не лечит |

Четыре независимых (что именно пропадает):

- `015aaf9d` recall 0.928 — список версий: потеряны `версия:` ×7, `(п. 1.9):` —
  list-collapse, P1c (list rewrite);
- `9f716b6a` recall 0.951 — `Тема:`, `Цель:`, `Формат:`, `Участники:` без буллета —
  тот самый `kv`-без-буллета, P1c;
- `8552867d` recall 0.970 — подписи подпунктов (`рекомендации`, `показателей:`,
  `загрузки:`) при flatten nested — P1c;
- `877fda58` recall 0.956 — короткий абзац-заголовок слит с соседним — минорный
  merge-баг, P1c/отдельный тикет.

Вывод: **p10/min — tail-warning, не гейт.** Гейт: `p50 ≥ 0.995`, `p90 ≥ 0.99`,
`p10 ≥ 0.97`; `min < 0.95` → warning + разбор, но не блокировка `PCT>0`. Все 4
независимых выше 0.92 уже сегодня, то есть min-gate 0.95 флапал бы на них
постоянно и не отражал бы реальную регрессию.

### 4.0.3 Хвост `block_coverage = 0`: 18 turn'ов, ручной разбор

Классификация на уровне turn'ов и на уровне уникальных worker-драфтов (в хвосте
есть повторы — ретраи одного хода с одинаковым summary):

| класс | turn'ов | уникальных драфтов |
|---|---|---|
| `formatter_worse` | 10 | 7 |
| `both_acceptable` (другой, но не худший deliverable) | 8 | 7 |
| `formatter_better` | **0** | **0** |
| `both_wrong` / `both_empty` | **0** | **0** |

Что именно ломается (по 7 уникальным `formatter_worse`):

- 4 случая — formatter отдаёт посторонний «План встречи на завтра» вместо анализа
  вложения (в т.ч. `e301d5fe`, `47625cae`);
- 1 случай — утечка роли: ответ начинается «Я — Formatter, модель,
  специализирующаяся на форматировании…» (`c5afc66a`);
- 1 случай — галлюцинация: formatter добавляет причины роста цен на иван-чай
  (плантации, урбанизация, логистика), которых нет в источнике (`d05a8bd5`);
- 1 случай — почти весь содержательный ответ worker'а заменён общим шаблоном
  плана (`87aaeb03`).

Ответ на вопрос A: **worker ни разу не был пустым или битым** в этом хвосте
(минимальный драфт — 445 символов, связный). Ответ на B: направление ошибки
одностороннее — formatter портит, а не спасает. Поэтому «single-writer закрывает
по построению» подтверждено данными, а не конструкцией: 10/18 turn'ов (5.4 % всех
186) сейчас отдают пользователю худший ответ, и worker-only режим вернул бы
корректный.

### 4.0.4 `both_acceptable` 8/18: thinning или enrichment (закрыто)

Длины worker → formatter по 8 «приемлемым» turn'ам (уникальные драфты):

| turn | worker | formatter | ratio | что делает formatter |
|---|---|---|---|---|
| `7241812f` | 7174 | 2458 | 0.34 | thinning: из письма делает сравнительную таблицу |
| `53f96659` | 2725 | 1671 | 0.61 | thinning: сжимает в разъяснение с таблицей |
| `ced332a8` | 1444 | 1431 | 0.99 | нейтрально, faithful rewrite |
| `9aa22668` | 446 | 542 | 1.21 | обёртка вокруг обрезанного источника |
| `f2525afa` | 2509 | 3207 | 1.28 | интерпретация письма, не новые факты |
| `f76d9969` | 611 | 1072 | 1.75 | структурирование обрезанного источника |
| `d23fd3c4` | 446 | 951 | 2.13 | структурирование обрезанного источника |
| `ea22c1f3` | 595 | 2084 | 3.50 | padding поверх вырожденного драфта |

`elaboration_rate` на всей популяции (187 пар, ratio > 1.2): **17 turn'ов = 9.1 %**;
`thinning` (ratio < 0.8, non-verbatim): **17 = 9.1 %**; near-equal — 81.8 %.
Но novelty-проверка (доля токенов formatter'а, которых нет у worker'а) показывает,
что **фактического обогащения нет**:

- высокий novelty у `d05a8bd5` (0.91) — галлюцинация, уже `formatter_worse`;
- высокая длина у `ea22c1f3`, `48fec11a`, `4a8280e6` — padding/обёртка вырожденного
  драфта (`197`, `143`, `19` символов);
- `d23fd3c4`, `f76d9969`, `15a9b15f`, `9aa22668` — обрезанный источник, formatter
  не может добавить корректные факты, только scaffolding;
- на содержательном драфте (≥990 символов) обогащение встречается в **2/187 = 1.1 %**
  (`3b1c69e8` — пересборка письма из сводки, `f2525afa` — интерпретация).

Итог: `elaboration_rate = 9.1 %` порог 10 % формально ниже, но содержательного
enrichment, который потерялся бы при `writer=worker`, — **1.1 %**. Гибрид
(`worker + enrichment-pass`) в P1 **не нужен**; то, что formatter добавляет,
— заголовки/callout-обёртки, и это закрывается промптом, а не вторым LLM-проходом.

### 4.0.5 Callout: baseline на той же популяции (закрыто, цифра исправлена)

`20.1 %` измерялись по 646 документам смешанного происхождения (экспорт включал
clarify/HITL-карточки), и **на P1-популяции не воспроизводятся**. На тех же 187
парах `formatter.task_id == researcher.task_id`:

| метрика | значение |
|---|---|
| `callout_presence_rate` (≥1 callout в turn'е) | **3/187 = 1.6 %** |
| callouts в worker-драфтах | 0 |
| тон всех трёх | `info` |

Распределение блоков (1 294 блока): paragraph 56.4 %, list 21.3 %, heading 19.7 %,
table 1.3 %, kv 0.6 %, steps 0.2 %, callout 0.2 %, divider 0.2 %.

Значит риск обратный прежней формулировке: **теряется callout не в каждой пятой
карточке, а в ~1.6 %** P1-популяции, и гейт `< 0.15` был бы провален по
построению (worker-промпт не даст 15 % callout'ов там, где formatter давал 1.6 %).
Callout-heavy документы — clarify/HITL, они остаются formatter-owned и P1 их не
трогает.

Действие: в промпт worker'а всё равно добавляется `> [!warning]` отдельной строкой
(дёшево, парсер уже понимает), а post-P1 монитор — `callout_presence_rate` с
гейтом **≥ baseline 1.6 %** (warning-полоса 1.0–1.6 %), не 15 %. Проверка
гипотезы «callout живёт в clarify/HITL» — по тегу `writer{owner}` в P1a.

### 4.0.6 Offline-оценка выигрыша (до `PCT>0`)

Из checkpoint-таймингов, «как если бы formatter не вызывался» (все 186 turn'ов
имеют оба тайминга):

- удаляемое время formatter'а: p50 **3.1–3.2 s**, p90 **11.9 s**, сумма 883–887 s
  на 185–186 turn'ов;
- доля formatter'а в (researcher + formatter): p50 **46.0 %**, p90 66.8 %.

Это верхняя граница выигрыша по латентности; она не включает upstream-узлы
(intent, enricher, critic), поэтому «39.5 s → 17 s» на `cd0f2fed` сходится:
удаляется ровно formatter-плечо. TTFV offline оценить нельзя — в checkpoint нет
per-token таймингов; после `dev`-деплоя нужен захват реального comparison-turn
(2 вложения, ≥6000 символов) как новый baseline (см. §6).

### 4.0.7 `cd0f2fed`

В локальном checkpointer есть только clarify-turn (3 блока) и 2-блочный ответ;
6018-символьный документ из трейса локально не сохранён (`dialog_turns` для треда
пуст). Поэтому per-turn цифры по нему недоступны, baseline снят на 186 локальных
turn'ах, а flagship-кейс фиксируется заново после деплоя (`scripts/find_trace.py`).

1. **Метрика.** Определить `structure_divergence` как в §5 (shingle containment +
   покрытие блоков), а не `len(formatter)/len(researcher)` и не Levenshtein по
   токенам: первое меряет expansion, второе — O(n²) на проде. Снять baseline на
   текущем `formatter`-output и убедиться, что метрика отличает `format_only`
   (должна быть ≈0) от double-generation turn'а.
2. **Fidelity детерминированного рендера.** Не `parse_failure_rate` — парсер не
   бросает исключений и не имеет такого счётчика; он деградирует молча. Мерить
   `structure_recall` по типам блоков на прогоне прод-ответов. Синтетический
   baseline (`markdown_to_content_document`, 2026-10-19):

   | Вход | Результат | Вердикт |
   |---|---|---|
   | GFM table | `TableBlock` | preserved |
   | `## heading` | `HeadingBlock` | preserved |
   | `- a` / `1. a` | `ListBlock` | preserved |
   | `> [!warning]` на отдельной строке + `> body` | `CalloutBlock` | preserved |
   | `- **Ключ**: значение` (2+ подряд) | `KeyValueBlock` | preserved |
   | `1. **Шаг**: тело` (2+ подряд) | `StepsBlock` | preserved |
   | `> [!warning] Важно` (title в строке маркера) | два `paragraph` | degraded |
   | `**Ключ**: значение` без `- ` | два `paragraph` | degraded |
   | code fence внутри list item | `list + code + list` (шаг разорван) | degraded |
   | nested bullets | плоский `ListBlock` (вложенность не представима моделью) | unsupported |
   | mojibake (cp1251→utf8) | валидный `paragraph`, детекта нет | undetected |

   Итог: 7/12 конструкций выживают — **но это не гейт**. Гейт — `information_fidelity`
   на реальных turn'ах (§4.0.1): **85 % (recall ≥ 0.99)**, strict `exact_parse` —
   79 % как диагностика. Объём фиксов по факту, а не по синтетике:

   | фикс | частота в worker-драфтах (187) | объём |
   |---|---|---|
   | `##`-заголовки обязательны в промпте worker'а | 12 turn'ов теряют 34 heading'а | **промпт, 0 кода** (Pre-P1 п.3) |
   | `> [!warning]` callout отдельной строкой в промпте | 3/187 = 1.6 % (гейт ≥ 1.6 %) | **промпт, 0 кода** (§4.0.5) |
   | `nested_bullet` → плоский с маркером `·` | **17.7–18.4 %** turn'ов | 0.5 дня + UX-check (§4 п.8) |
   | `kv` без буллета `**Label**: value` | 3.2 % turn'ов | 0.5 дня, одна regex-ветка |
   | `callout` с title в строке маркера | **0** turn'ов | не бюджетировать |
   | code fence в list item | **0** turn'ов | не бюджетировать; тикет отдельно |

   Поправка к прежней оценке «2 regex-ветки»: реальных дефекта два, и один
   (`nested_bullet`) — не regex. Частоты callout пересчитаны на P1-популяции
   (§4.0.5): 1.6 %, а не 20.1 % из смешанного экспорта.
3. **Промпты.** Два разных контракта, не один с твиками: `writer=worker` — полный
   GFM-ответ (обязательные `##` для секций, GFM-таблица для сравнений, callout —
   только `> [!warning]` отдельной строкой); `writer=formatter` — текущий
   structured draft. Оба требования (`##` + callout) — **один PR**. Отдельный
   прогон golden-set.

   `##`-контракт — **гипотеза** с ожидаемым диапазоном 88–96 % strict
   (12 heading-turn'ов + 5 list-consequence, LLM-комплаенс 70–100 %). P1 **не
   стартует**, пока `measure_verbatim_parse.py` не перезапущен после правки и не
   подтвердил `information_fidelity ≥ 0.90` и `p10 ≥ 0.97`. Если 0.85–0.89 —
   промпт итерируется до P1, а не после.
4. **HITL-риск §3.4** — shadow-замер `hitl_choice_cards_minted / turns`, до включения
   `PCT>0`. Текущий baseline (LLM-owned, 646 документов): **19 menu-shaped карточек на
   646 turn'ов = 2.94 %** всех ходов и **10.3 %** ходов со списком. При
   `writer=worker` каждый `- пункт` становится `ListBlock` детерминированно, поэтому
   это число — нижняя граница, а не ожидание; гейт — не выше baseline на
   worker-owned маршруте.
5. **Rollout-единица.** Бакетить по `thread_id` (стабильность формата внутри
   диалога), фиксировать `writer` в контексте turn'а один раз. По `task_id` —
   не бакетить: это уникальный id хода, «sticky» исчезает и формат мигает каждый
   turn.
6. **Хвост-эвал `block_coverage = 0`** — ✅ пройден (§4.0.3): 18 turn'ов / 14
   уникальных драфтов, `formatter_better` и `both_empty` — по нулям,
   `formatter_worse` — 7/14. Условие «single-writer закрывает по построению»
   доказано данными; rubric worker-owned калибруется против этих же 14 драфтов.
7. **Offline deterministic baseline** — ✅ снят (§4.0.6): удаляемое плечо p50 3.1 s /
   p90 11.9 s, доля formatter'а 46 % от (researcher+formatter). Осталось после
   `dev`-деплоя: захват реального comparison-turn (2 вложения, ≥6000 символов) с
   per-token TTFV — в checkpoint per-token таймингов нет, поэтому TTFV offline
   не измеряется.
8. **Nested-flatten UX-check** (новый, до `PCT>0`). Flatten меняет вид 18 % ответов,
   поэтому 5–10 реальных nested-turn'ов прогоняются через flatten на golden-set
   rubric и сравниваются с baseline. Если rubric падает > 5 % — flat недостаточен,
   `ListItem(children)` тянется в P1c (+0.5–1 день), а не в отдельный ADR.
9. **Enrichment-проверка** — ✅ закрыта (§4.0.4): `elaboration_rate` 9.1 %, но
   содержательное обогащение на здоровых драфтах — 1.1 % (2/187), остальное
   scaffolding/галлюцинации. Гибрид `worker + enrichment-pass` в P1 не нужен.

## 5. Фазы

| Фаза | Объём | Что даёт |
|---|---|---|
| **P0. Метрики + Pre-P1** | 2–2.5 дня | `structure_divergence`, `writer{owner}`, `node_output_tokens`, `ttfv_seconds`, `hitl_cards_minted`; **блокирующий гейт** `information_fidelity ≥ 0.90` после промпта; хвост-эвал 14 драфтов; offline-baseline |
| **P1a. Worker writer (shadow)** | 1 день | writer выбирается и логируется, рендер старый; rubric + HITL-замер + проверка, что callout живёт в clarify/HITL |
| **P1b. Worker writer (live)** | 1.5–2 дня | ось + политика + researcher-стрим + deterministic formatter; один PR на промпт (`##` + callout-синтаксис); удаляемое плечо p50 3.1 s / p90 11.9 s (§4.0.6), TTFV 17 s → ≈2 s |
| **P1c. Парсер: `nested_bullet` + `kv`-без-буллета** | 1–2 дня | 17.7–18.4 % и 3.2 % драфтов; +UX-check nested (§4 п.8); `ListItem(children)` — только если rubric падает > 5 % |
| **P2. Formatter-owned TTFT** | 1 день | для `format_only`/clarify первый блок/токен сразу; `first_token_fallback_watch` больше не нужен на formatter-owned |
| **P3. Tiering/FinOps** | 0.5–1 день | `nano` только для коротких social; динамический `max_tokens` уже есть; потолок p95 как гейт |
| **P4. Удаление `formatter_delta`** | 0.5 дня | отдельный PR, см. §7 |

Роллаут P1: `ANSWER_WRITER_MODE=worker|formatter` + `ANSWER_WRITER_ROLLOUT_PCT`
(sticky по `thread_id`, та же семантика двух ключей, что `FORMATTER_ROLLOUT_PCT`;
общий helper вынести в `core/observability/rollout.py`, не копировать). Это **новая**
ось, не дубль `FORMATTER_MODE`: откат — `PCT=0`, без деплоя.

## 6. DoD / гейты

- `layout_shift_total{contract="structured_incremental"} == 0` (сохраняется).
- **Pre-P1, блокирующий (information gate):** доля verbatim-turn'ов с
  `token_recall ≥ 0.99` и непустым документом — **сейчас 85.0 %**, порог **≥ 90 %**
  после правки промпта. Плюс `p50 ≥ 0.995`, `p90 ≥ 0.99`, `p10 ≥ 0.97`
  (сейчас p50/p90 = 1.000, p10 = 0.9751). `min < 0.95` — **tail-warning**, не гейт
  (4 независимых парсер-бага сидят на 0.928–0.970, min-gate 0.95 флапал бы
  постоянно, §4.0.2).
- **Pre-P1, диагностика (strict):** `exact_parse ≥ 0.80` (сейчас 79.0 %).
  kv/steps promotion сюда **не входит как failure** — это shape-only (6 из 21
  strict-провала), текст сохранён; двойной счёт убран (§4.0.1). `PCT=5` от strict
  не зависит.
- `structure_divergence` p95 < 0.3 на worker-owned маршрутах. Baseline до включения
  (186–187 turn'ов, 2026-10-19): p50 0.036 / p95 0.975, при этом 22.6 % turn'ов уже
  ≥ 0.3 — гейт меряется как **дельта** на worker-owned, а не как абсолют: медиана
  уже проходит, fail идёт из хвоста. Формула:
  `1 - |shingles(final) ∩ shingles(worker)| / |shingles(final)|` по нормализованному
  тексту (whitespace-collapse, lowercase) с шагом 3 слова, плюс `block_coverage` —
  доля блоков финального документа, чей текст содержится в источнике. Считается
  O(n), без embed-вызовов: сетевой эмбеддинг на каждом turn'е дороже самой метрики и
  не отличает «переписал» от «переставил слова» лучше шинглов.
- **`block_coverage` после P1 меняет смысл — разделить гейт:**
  - pre-P1 (baseline sanity): p50 1.000 / mean 0.777 — метрика работает;
  - post-P1 `worker-owned`: **строго 1.0**. Не «регрессия качества», а smoke-test:
    любое отклонение значит, что deterministic-рендер не справился и turn утёк в
    LLM-path. Лечится фиксом парсера, а не откатом `PCT=0`;
  - post-P1 `formatter-owned`: rubric, не `block_coverage` (другой baseline).
- TTFV p95 на worker-owned: ≤ 3 s (сейчас на `cd0f2fed` ≈ 17 s; offline-базис —
  удаляемое плечо p50 3.1 s, §4.0.6).
- Total p95 на `cd0f2fed`-классе: ≤ 20 s (сейчас 39.5 s).
- **Post-deploy захват flagship-кейса:** в первые 24 ч после `PCT=5` сохранить
  реальный comparison-turn (2 вложения, ≥6000 символов) как новый baseline в §6 и
  приложить trace-id. `cd0f2fed` локально не воспроизводим (§4.0.7), поэтому без
  этого захвата цифра «17 s» останется оценкой.
- **Callout (post-P1 monitor):** `callout_presence_rate` на worker-owned
  **≥ 1.6 %** (baseline той же популяции: 3/187, §4.0.5), warning-полоса
  1.0–1.6 %. Порог 15 % из прежней редакции **снят**: он был выведен из
  смешанного экспорта 646 документов и на P1-популяции недостижим по построению.
- **`nested_bullet` (post-P1 monitor):** доля worker-owned turn'ов с flatten'ом без
  потери текста (`token_recall` по turn'у) — не ниже baseline; rubric nested
  прогоняется до `PCT>0` (§4 п.8).
- Качество: golden-set по shape, не один общий — 4×10: `prose`, `comparison`,
  `plan`, `format_only`, у каждого свой rubric (`comparison` валит кривую таблицу,
  даже если текст хорош); rubric не хуже текущего formatter-output, иначе
  worker-owned не включается. Для worker-owned rubric калибруется против 14
  уникальных драфтов из хвоста §4.0.3 (7 `formatter_worse`, 7 acceptable).
- HITL: `hitl_choice_cards_minted / turns` на worker-owned не выше baseline
  (shadow-замер из Pre-P1).
- Тесты: ось/политика — unit (таблица маршрутов); partial-json string — параметризация
  по границам чанков; fidelity — таблица §4 зафиксирована unit-тестами (table ✔,
  callout/kv/nested — известная деградация, не регресс); integration — SSE:
  `answer_delta` без `replace`, финальный документ ⊇ показанного; revision — ровно
  один `replace` на эпоху.
- FinOps: `palatium_llm_cost` на turn падает ≈ вдвое на worker-owned (сейчас двойная
  генерация).

## 7. `formatter_delta`: удалить отдельным PR

Backend не эмитит событие, `FORMATTER_DEBUG_STREAM_DELTAS` никем не читается
(`core/config/formatter.py:25` — только объявление). Удалить:

- `FormatterConfig.debug_stream_deltas` + ключ в `env/.env*` (7 файлов; parity-тест
  `test_env_template_parity.py`).
- FE-обработчик `web/src/api/client.ts:502`, `previewTextFromFormatterJson`
  (`:376`), оба вызова в `ChatShell.tsx` (`onFormatterDelta`) и тест
  `web/tests/unit/formatter-stream-preview.test.ts`.
- Комментарии/докстроки `intent_graph_runner.py:226,266`, `docs/architecture/streaming.md:30`,
  `.cursor/plans/evolution-to-big-tech.md:159`.
- **Файл `tests/unit/test_formatter_debug_stream.py` не удалять, а переименовать**
  (`test_formatter_markdown_stream.py`): несмотря на имя, там живые тесты
  `text_delta` + dual `answer_delta` + единственного `replace`. «Удалить по имени» —
  потеря трёх контрактных проверок.
- Acceptance: `rg "formatter_delta|FORMATTER_DEBUG_STREAM_DELTAS"` = 0 (кроме истории
  планов и `docs/diagnostics/p0/`); SSE-тесты зелёные; в `web/` нет `skip`/`todo` на
  удалённый обработчик.

## 8. 2026 / Big Tech — на что опираемся

- **OpenAI Responses API**: один поток на turn, tool calls инлайн, structured output
  стримится частично; отдельного «второго форматтера» нет.
- **Anthropic streaming + tool use**: аргументы приходят частями, UI обновляется
  инкрементально; финальный объект не переписывает показанное.
- **Google ADK / Gemini**: bidi-стрим финального ответа; рендер — на клиенте.
- **Vercel AI SDK `streamText` / `streamObject`**: партиальный объект рендерится
  сразу, финальный — его надмножество.
- **LangGraph `stream_mode="custom"`**: кастомные кадры из узла — у нас уже реализовано
  через `TurnSseBridge`; менять транспорт не нужно.
- **FrugalGPT-style cascades / tiering**: это cost/latency-оптимизация второго
  порядка, применяется после устранения лишней работы, не вместо неё.
- **Tail-at-scale (hedged requests)**: не применяем — удваивает стоимость и не лечит
  двойную генерацию.

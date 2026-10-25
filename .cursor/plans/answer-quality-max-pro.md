# Answer quality MAX PRO — восприятие, доступность, атрибуция, судья

Статус: все волны реализованы (2026-10-24): W0a, W0b, W1 (сервер + клиент), W2, W3a,
W3b-1, W3b-2 (по спеке `docs/source-citation-highlight.md`), W4, W5, W6, W7a, W7b,
W7b-UI, W7b-UI/HITL (конверт `revision` в ответе на карточку — `HitlRespondResponse`).
Открытых пунктов нет; осознанно отложено — ручные E2E для подсветки места в источнике.
Дополняет (не переписывает):

- `structured-streaming.md` — транспорт и партиалы (`F1`/`F2` сделаны);
- `response-shapes.md` — ось формы, волна 2 (`block_delta`) сделана;
- ADR 0005 — `ContentDocument` остаётся единственным контент-контрактом;
- нормы: 040 (метрики/судья), 050/055 (политика вместо хардкода), 075 (эвалы),
  084 (фронтенд), 005 (спека до кода), 086 (док как код).

## 1. Проблема

Корректность ответа (валидная схема, отсутствие усечений, один `replace` за turn)
достигнута, но остаются четыре разрыва, которые не ловятся ни Pydantic, ни
Playwright-счётчиком layout shift:

1. **Восприятие.** `structured_incremental` молчит до первого закрытого блока;
   частичный `<table>`/`<cards>` рисовать нельзя, а частичный абзац — можно.
   Сейчас это не выражено политикой: решение «стримить или ждать» принимается
   неявно в сканере.
2. **Доступность.** `role="log"`/`aria-live` на ленте сообщений отсутствует
   (`ChatShell.tsx`), а наивное включение на каждом дельта-кадре даёт лавину
   объявлений. Нужен отдельный a11y-канал, живущий по закрытым блокам.
3. **Атрибуция.** `meta.source_refs` — это подписи файлов из fence
   (`domain/attachments/citations.py`), а не позиции в источнике. Провайдерская
   метаданные цитат в `LLMCompletion` вообще не доходят (`content: str`), поэтому
   «клик → точное место» физически нечем построить.
4. **Диагностика.** Одна «доля нарушений» смешивает три класса отказов, которые
   лечатся разными командами, а линтера, который бы эти нарушения производил,
   в `dev` нет.

## 2. Аудит: что реально есть в `dev` (2026-10-23)

| Заявлено в исходном плане | Фактически |
|---|---|
| Базовый план из 14 разделов реализован | Частично. `schema_first`, strict schema, repair, fast path, response shapes, `block_delta` — есть. Подсистемы lint-правил L01–L12 **нет**: поиск `lint` по `src/` пуст |
| `block_text_delta` | Нет. `PartialDocumentScanner` отдаёт блок только целиком (`partial_document.py`) |
| `TTFVF ≤ 300 мс` | Нет ни метрики, ни skeleton-контракта. Есть `palatium_sse_ttft_seconds` (сервер, первый кадр) — клиентская часть закрыта W1-клиент |
| `aria-live` политика | Нет. `aria-live` есть только у счётчика composer (`ChatShell.tsx:1515`) — закрыто W2 |
| `CitationSpan` с `start_index`/`end_index` | Нет. `Citations`-поля не проходят через `LLMCompletion` (`domain/llm/models.py`) — только filename-chips |
| Decomposed judge, 4 измерения | Нет. Есть holistic `LlmJudgeGrader` (nightly, `evals/llm_judge.py`) + grounding judge |
| Три раздельные метрики | Нет. В реестре 040 только `palatium_sse_ttft_seconds` и `palatium_sse_layout_shift_total` |
| Golden set с «защитными» кейсами | `evals/tasks.json` — детерминированные проверки, не калибровочный набор |
| `verbosity_budget`, `revision_of` | Нет. `ContentDocument` не имеет ни поля, ни стабильных id блоков (W7a закрыл ось бюджета; `revision_of` — W7b) |

Следствие: `semantic_error_rate` и «backtesting линт-правил с FP ≤ 1%» в исходном
плане опираются на несуществующий слой. Первая волна — **создать линтер**, а не
собирать его метрику.

## 3. Scope

- `src/palatium_ai/domain/content/` — lint-политика, модель цитат, `verbosity_budget`.
- `src/palatium_ai/application/agents/formatter/` — запись метрик, стратегия показа
  блоков, few-shot промпты, серверный diff для `revision_of`.
- `src/palatium_ai/domain/llm/models.py` + `infrastructure/llm/litellm_adapter.py` —
  проброс провайдерских citations/annotations.
- `src/palatium_ai/core/observability/metrics.py` — только новые имена из этого плана.
- `web/src/components/ChatShell.tsx`, `web/src/lib/` — live-region, TTFVF-метки,
  подсветка источника.
- `web/e2e/` — a11y-сценарии; `scripts/` — offline backtesting.

## 4. Вне scope

- Второй контент-контракт (`Answer`/`RichResponse`) — запрещён ADR 0005.
- Runtime-судья для всех ходов: 040 уже требует судью для критичного выхода;
  менять норму — отдельный PR (088), не побочный эффект этой работы.
- Новый провайдер LLM, новый MCP-инструмент, новая схема БД.
- VoiceOver/NVDA-автоматизация в CI: ручной чек-лист (086: не врать про автоматизацию).

## 5. Волны

### W0a — Lint как доменная политика (предусловие всей работы) — реализовано

`domain/content/lint/` (`engine.py`, `rules.py`, `models.py`):

```python
LintRuleId = Literal[
    "internal_marker_leak",
    "dangling_citation",
    "duplicate_prose",
    "markdown_residue",
    "empty_section",
]


class LintFinding(BaseModel, frozen=True):
    rule_id: LintRuleId
    severity: Literal["error", "warning"]
    block_index: int | None


class ContentLint:
    @classmethod
    def run(cls, document: ContentDocument) -> LintReport: ...
```

- Правила — чистые функции, без LLM и I/O; проверяются unit-тестами без моделей.
- Контекста хода у линтера нет: `ContentDocument` + `meta.source_refs` достаточно
  для всех пяти правил. `LintContext` появится вместе с `verbosity_budget` (W7),
  когда правилу действительно понадобится ось, а не «на будущее» (010).
- `code`/`formula` не проверяются: это текст пользователя, sanitizer их тоже
  пропускает (055).
- `internal_marker_leak` — детектор, а не второй словарь: он вызывает
  `InternalVocabularyPolicy.has_terms` + regex на `[[page N]]`/`mcp:<server>.<tool>`.
  Hit после штатной санитизации означает дыру в guard'е, а не повод переписать текст.
- Форма ответа здесь **не** проверяется: её владелец — `ShapeRecipePolicy`
  (`palatium_response_shape_total` уже несёт mismatch). Вторая проверка разошлась бы.
- В W0a линтер **измеряет, но не переписывает** документ: repair остаётся там,
  где он есть, иначе lint станет вторым источником правок.
- Вызов — один на ход: `FormatterAgent._record_content_lint` после
  `_record_shape_verdict`, для обоих контрактов генерации и fallback-документов.
- Метрика: `palatium_content_lint_findings_total{rule, severity}` (кардинальность
  ограничена реестром правил). Проза в лог не пишется — только rule ids и счётчики.
- DoD выполнен: `tests/unit/test_content_lint.py` (13 кейсов, включая negative:
  code-блок, цитата в пределах источников, не-соседний дубль).

### W0b — Три метрики с разными знаменателями — реализовано

| Метрика | Знаменатель | Что диагностирует |
|---|---|---|
| `palatium_formatter_schema_total{path,outcome}` | `path=schema_first`; rate = `valid / (valid+invalid)` | промпт, constrained decoding, выбор модели |
| `palatium_content_lint_findings_total{rule,severity}` → `semantic_error_rate` (PromQL, дашборд) | только schema-valid документы | линтер и бизнес-правила |
| `palatium_judge_score{dimension}` (W4) | стратифицированная выборка судьи | судья и модель |

Решения, принятые при реализации (расходятся с первой редакцией — она ошибалась):

- **`empty_blocks` не в знаменателе `schema_validity`.** Документ схему прошёл;
  модель выбросила содержимое — это дефект контента. Сворачивать его со схемой
  значит снова смешивать два класса отказов, ради разделения которых и вводится
  счётчик. Он живёт отдельной серией и отдельным порогом (1%).
- **`unsupported` не в знаменателе.** Провайдер отказал в `stream` + `json_schema`,
  вердикта по схеме не существует; делить на такие попытки — занижать метрику
  инфраструктурой.
- **Транспортные ошибки не пишутся в этот счётчик.** Их владелец —
  `palatium_agent_errors_total` (`schema_first_llm_stage_failure`). Второй счётчик
  того же факта — расхождение (050).
- **`repaired` для legacy не вводится.** `generate_document` не возвращает число
  попыток, а у deprecated-пути (удаление — Phase 4) нет потребителя этой цифры
  (010: тип/метрика без потребителя не добавляется). Legacy outcomes: `valid` |
  `fallback`.
- **`node_name="schema_first:*"` удалены.** Исходы больше не дублируются в
  `palatium_agent_request_duration_seconds`: там осталась латентность по когорте
  (`formatter:schema_first` / `formatter:legacy`) и пути деградации `emit:*`.
  Документ и PromQL обновлены в том же PR (086).
- Закрытые наборы — `FormatterGenerationPath` / `FormatterSchemaOutcome` в
  `domain/policies/types.py` (одно объявление, 010), а не литералы на месте вызова.
- **Прод-алерт, не PR-гейт:** `schema_validity_rate < 0.995` за 30 мин блокирует
  рампу (`PCT=0`), но не сборку. PR-гейт остаётся offline (075).

### W1 — Матрица «тип блока → стратегия показа» — реализовано (сервер и клиент)

`domain/policies/stream_display.py`, закрытый Literal:

```python
StreamDisplay = Literal["text_delta", "skeleton", "on_close"]
```

| Блок | Стратегия |
|---|---|
| `paragraph` | `text_delta` (единственный блок, где частичный текст не врёт) |
| `heading` | `on_close` (заголовок — один кадр `document_title`/`block_delta`) |
| `list`, `steps`, `table`, `kv`, `chart` | `skeleton` до закрытия блока |
| `code`, `formula`, `callout`, `divider`, `widget` | `on_close` — частичный код/формула = misinformation |

- Политика — единственное место решения; `PartialDocumentScanner` спрашивает её,
  а не хардкодит тип. Неизвестный тип → `on_close` (fail-safe).
- `text_delta` для `paragraph`: `_decode_json_string_prefix` разбирает **открытую**
  строку JSON инкрементально (escape, `\uXXXX` + суррогатная пара). Незавершённый
  escape и одиночный суррогат не рисуются — ждём, а не показываем неверный символ.
  `safe_cut` (020) придерживает хвост, который может оказаться половиной внутреннего
  маркера. Закрывающий фрейм досылает остаток из **валидированного** блока, поэтому
  напечатанный префикс + остаток == `block.text` (superset, `layout_shift == 0`).
- Тип блока обязан быть известен до первого кадра: если `"type"` ещё не пришёл,
  префикс не эмитится — иначе заголовок/ячейка таблицы ушли бы в `text_delta`
  задним числом.
- Фрагменты одного абзаца идут с `continues_prose=True`: без `\n\n` и без
  `strip()` — иначе на границе дельты склеиваются слова.
- **TTFVF — клиентская метрика (W1-клиент, реализовано).** Меряется
  `web/src/lib/firstVisual.ts`: старт снимается синхронно в `send()` (до первого
  `await`), конец — второй `requestAnimationFrame` после commit'а, т.е. после
  paint кадра с заглушкой; значение пишется в таймлайн как
  `palatium:ttfvf` (с `detail.budgetMs`) и читается E2E-гейтом
  `web/e2e/ttfvf.spec.ts` против `TTFVF_BUDGET_MS = 300`. В сеть ничего не
  уходит: RUM-эндпоинта у виджета нет и не должно быть (020 — данные остаются
  у хоста). Серверная величина, которую стоит гейтить отдельно, —
  `palatium_sse_first_block_seconds` (submit → первый `block_delta`).
- **Отдельного skeleton-блока НЕ добавляем — осознанное отступление от
  исходной формулировки.** `StreamDisplayPolicy` документирует, что на проводе
  `skeleton` и `on_close` неотличимы: у ещё не пришедшего блока нет типа, значит
  типизированную заглушку построить нечем, а generic-заглушка уже есть — орб
  фазы (`ThinkingIndicator`), который рисуется синхронно на submit и занимает
  ровно колонку будущего текста (`.msg.is-waiting { padding-left: 44px }`).
  Второй placeholder рядом с орбом дал бы два конкурирующих «идёт работа», поэтому
  W1-клиент закрывает не форму, а **измеряемость**: раньше «пользователь видит
  отклик ≤ 300 мс» нельзя было ни проверить, ни заметить регресс.
- `prefers-reduced-motion` уже учтён в `web/src/styles.css`.

### W2 — Доступность как отдельный канал — реализовано

- Визуальная лента: `role="log"` + `aria-live="off"` — постоянно, а не «на время
  стриминга»: переключение `off → polite`, когда текст уже в DOM, часть пар
  «браузер + скринридер» не объявляет (тот же запрет, что и для канала). В
  `ChatShell` это `<div part="transcript">`, а не `<main>`: лендмарк принадлежит
  странице-хосту, а переопределять роль `<main>` спецификация не разрешает.
- Отдельный `sr-only` канал (`role="status"`, `aria-live="polite"`,
  `aria-atomic="true"`) вне ленты: `components/LiveAnnouncer.tsx`.
- **Содержимое слота ЗАМЕНЯЕТСЯ, а не дописывается.** `aria-atomic="true"`
  объявляет регион целиком, поэтому append перечитывал бы весь ответ на каждый
  блок. Слотов два, они чередуются по чётности `seq`: одинаковый текст подряд
  (два идентичных абзаца) всё равно меняет DOM, а регион никогда не переключает
  `aria-live` (`off → polite` после появления контента часть пар не объявляет).
- Правила «что слышно» — `lib/streamA11y.ts` (чистый модуль, без DOM): проза
  целиком; таблица/код/формула — формой («столбцов N, строк M»), не ячейками;
  `list`/`steps`/`kv` — одно объявление на блок, до 5 элементов, дальше «и ещё N»;
  `divider` не объявляется вовсе.
- Батчинг обязателен: SSE-парсер разбирает все кадры одного сетевого чанка в
  одном тике, и без буфера (микрозадача на сброс) React схлопнул бы `setState`
  до последнего блока. `tests/unit/live-announcer.test.tsx` это фиксирует.
- `doc_end` — одно агрегированное «ответ готов» при `result` (+ «требуется ваша
  проверка»); заголовок, не пришедший отдельным кадром, склеивается с финалом в
  ОДНО объявление (два `announce` подряд схлопнулись бы и заголовок потерялся).
- Ошибка стрима объявляется (`a11y.error`) — иначе после «ответ готов» тишина.
- `document_title` объявляется один раз, до первого блока.
- Гейт: `tests/unit/stream-a11y.test.ts` + `tests/unit/live-announcer.test.tsx`
  (правила и дедупликация), Playwright + axe (`npm run test:a11y`) — разметка;
  поведение VoiceOver/NVDA — ручной чек-лист `web/e2e/a11y-announcements.manual.md`
  (длинный ответ, ответ с таблицей).
- Гейт: Playwright + axe (`npm run test:a11y`) ловит разметку; поведение
  VoiceOver/NVDA — ручной чек-лист в `web/e2e/` (два сценария: длинный ответ,
  ответ с таблицей).

### W3 — Цитаты: два разных якоря — W3a реализовано

Ключевая ошибка исходного плана: `start_index`/`end_index` у OpenAI — это позиции
**в тексте ответа**, а не в источнике; у Gemini `groundingSupports` — сегменты
ответа; у xAI — только URL. Смешивать их в одном `CitationSpan` нельзя.

```python
CitationAnchor = Literal["char_location", "page_location", "content_block_location", "url_only"]


class CitationRef(BaseModel, frozen=True):
    source_ref: str
    quote: str | None = None
    page: int | None = None
    source_range: tuple[int, int] | None = None  # только если провайдер дал позиции в источнике
    answer_range: tuple[int, int] | None = None  # позиции в ответе (OpenAI/Gemini)
    anchor: CitationAnchor
```

- `source_range is None` — честное «точное место недоступно», а не подставленные
  нули.
- `domain/content/citations/normalizer.py` — чистая функция: нормализация
  whitespace **только для сопоставления quote**, сам `quote` не мутируется;
  цитаты с `answer_range` за пределами текста отбрасываются; считается
  `emitted-vs-resolved`.
- Предусловие: `LLMCompletion`/`LLMStreamDelta` получают `citations`/`annotations`,
  адаптер LiteLLM их пробрасывает. Без этого волна мертва — сейчас metadata
  отбрасывается на границе.
- Метрика: `palatium_citation_resolution_total{anchor,outcome}`.
- **Открытый вопрос:** UI-просмотрщика источника с подсветкой в `web/src` нет
  (есть только chips). W3 делится: W3a — модель+нормализатор+метрика; W3b —
  просмотрщик и подсветка, отдельная спека (это новый экран, не «добавить onClick»).

**W3a сделано (2026-10-23):**

- `domain/content/citations/`: `CitationRef` (+`CitationAnchor`, validator: `url_only`
  не несёт позиций в источнике, спаны только `0 <= start < end`) и нормализатор
  `classify` / `normalize_citations`.
- `LLMCompletion.citations` — метаданные больше не отбрасываются на границе;
  `infrastructure/llm/citation_mapping.py` декодирует оба реальных формата
  (OpenAI `url_citation` start/end → `answer_range`; Anthropic
  `char_location` / `content_block_location` / `page_location` → `source_range` / `page`).
  Неизвестная позиция остаётся `None` — не `0` и не clamp.
- Метрика `palatium_citation_resolution_total{anchor,outcome}` (`resolved` /
  `out_of_range` / `unanchored`); в знаменателе **все** эмитированные цитаты,
  включая отброшенные — иначе rate улучшается отбрасыванием сложных кейсов.
- Потребитель: `FormatterAgent._record_citations` на `schema_first`-пути
  (ответ не меняется). Legacy-путь и Researcher подключаются, когда реально начнут
  передавать провайдеру цитируемые документы — до тех пор хук был бы мёртвым кодом.
- **Осталось на W3b (нарезано явно):** `DocumentMeta`-уровень отображения (chips
  сегодня строятся из `meta.source_refs`), просмотрщик источника с подсветкой,
  `answer_range` в UI.

**W3b, часть 1 — якоря в контракте и просмотр цитат (2026-10-24, реализовано):**

- `DocumentMeta.citations` (`domain/content/content_document.py`) —
  `Annotated[..., SkipJsonSchema()]`. Поле есть на проводе server → client, но
  **отсутствует в strict-схеме провайдера**: strict требует все свойства, и
  перечисленное поле модель обязана была бы заполнить — то есть выдумать смещения,
  которых у неё нет. Якоря прикрепляются после валидации в
  `FormatterAgent._run_schema_first` (`_resolve_citations` → `model_copy`);
  блоки к этому моменту уже отрисованы, meta layout не меняет (инвариант W1).
- UI `components/CitationSources.tsx` + `lib/citations.ts`: один чип на **источник**
  (не на цитату), чип — disclosure-кнопка (`aria-expanded`/`aria-controls`,
  Escape закрывает, фокус остаётся на чипе). Панель показывает дословный `quote`
  и только ту позицию, которую сообщил провайдер: `page` → «Стр. N»,
  `source_range` → диапазон символов, иначе — «точное место в источнике
  недоступно». `href` — только для http(s) (`javascript:`/`data:` отбрасываются:
  `source_ref` — недоверенный ввод, 020). Без `citations` (старые документы
  и сохранённые ответы) остаются прежние чипы из `meta.source_refs`.
- Тесты: `test_formatter_schema_first.py` (якорь доходит до клиента **и** не
  появляется в схеме провайдера), `web/tests/unit/citations.test.ts`,
  `web/tests/unit/citation-sources.test.tsx`, кадр `citations` в матрице
  состояний; `noEnglish` в кадре ловит непереведённые подписи.
- **W3b-2 — реализовано (2026-10-24):** подсветка места цитаты **в тексте источника**,
  спека — `docs/source-citation-highlight.md`. Единственное координатное пространство —
  `AttachmentContent.safe_text`; источник истины — `quote` (смещение от провайдера только
  подсказка и проверяется цитатой; `content_block_location` не даёт подсветку вовсе).
  `CitationLocator` (`domain/content/citations/locate.py`) — чистая политика с закрытым
  набором исходов (`declared_range` / `quote_match` / `ambiguous_quote` /
  `quote_not_found` / `no_text`); `CitationRef.source_id` заполняется сервером и только
  при однозначном совпадении fence-метки (`attachment_ids_by_label`);
  `AttachmentContent.text_masked` фиксирует редакцию текста при приёме (PII-маска не
  меняет `scan.action`); `POST /api/attachments/{id}/citation-locate` отдаёт окно
  ≤ `CITATION_WINDOW_CHARS` с `Cache-Control: no-store`; UI — `SourcePanel` +
  кнопка у цитаты. Метрика — `palatium_citation_highlight_total{outcome}`.
- `answer_range` в UI не используется намеренно: после `schema_first` это
  смещение в сыром ответе провайдера, а не в отрисованных блоках.
- `LLMStreamDelta.citations` осознанно НЕ добавлен: у стрима нет потребителя, а
  аннотации провайдеры присылают на завершённом сообщении (010: тип без потребителя).

### W4 — Судья: декомпозиция, но без отмены 040 — реализовано

- Четыре независимых вызова: `correctness`, `completeness`, `groundedness`, `tone`;
  у каждого своя рубрика и свой `palatium_judge_score{dimension}`.
- Провайдер судьи ≠ провайдер генератора (040), tier не ниже `standard`; расход —
  `palatium_agent_cost_usd_total{direction="judge"}`.
- 040 требует судью **перед финализацией критичного выхода безусловно**.
  «10–20% трафика» может быть только дополнительной телеметрией поверх гейта:
  снижение покрытия — правка нормы 040 отдельным PR, не эта волна.
- PII: ответ с `contains_pii` нельзя отправлять внешнему судье (020/060) —
  маршрут в внутреннюю модель или `requires_review`.
- Расхождение измерений > 0.3 — сигнал о промпте/модели, не автоматический
  `requires_review`.

**W4 сделано (2026-10-23):**

- `JudgeDimension` + `DimensionScore` / `DecomposedVerdict` в `domain/agents/evals.py`
  (закрытый набор, одно объявление, 010).
- `domain/policies/judge.py` — `JudgePolicy.evaluate` (чистая, без I/O) и
  `JudgePolicy.route` (PII не уходит наружу). Гейтуются только оси с нормой в 040:
  `correctness ≥ 0.6`, `groundedness ≥ 0.8`; `completeness`/`tone` — измеряются,
  но не блокируют (иначе порог был бы выдуман). Ось без оценки → `missing` →
  `requires_review`, никогда не «pass» (050 Silent failure).
- `application/agents/evals/decomposed_judge.py` — `DecomposedJudgeGrader`
  (`kind="decomposed_judge"`): по одному вызову на ось, своя рубрика в
  `judge_prompts.DIMENSION_RUBRICS`, метрики `palatium_judge_score{dimension}` и
  `palatium_judge_failed_total{dimension}`. Поддержка cassette (fixture без оси не
  подтверждает ось) и live-LLM через `EvalJudgeClientFactory`.
- Opt-in: `judge_mode: "decomposed"` в nightly-задаче (старые baseline не выражают
  четыре оси, поэтому переключение per-task, 075). Режим в отчёте —
  `decomposed_judge:<cassette|fixture|runtime>`.
- PII: `PALATIUM_EVAL_INTERNAL_JUDGE_PROVIDER` — внутренний судья; его нет →
  `requires_review` без единого вызова (020).
- **Не сделано осознанно:** tier судьи ≥ `standard` не проверяется кодом — тариф
  задаётся конфигом провайдера (`PALATIUM_EVAL_JUDGE_MODEL`), инспектировать его из
  eval-пути нечем; «10–20% трафика» тоже не реализовано — 040 требует гейт
  безусловно, а выборочность была бы правкой нормы, не этой волной.

### W5 — Backtesting линтера — реализовано

- Предусловие: W0a + корпус. Источник — `dialog_turns.payload` (там персистится
  `ContentDocument`); выгрузка анонимизируется, PII не покидает контур (060).
- `scripts/backtest_lint.py`: прогон правил по корпусу, отчёт `rule → hits/rate/
  response_shape`, без записи в БД.
- «FP ≤ 1%» честно считается только на **курируемом** наборе легитимных ответов:
  у прод-корпуса нет разметки, поэтому доля срабатываний ≠ FP.
- Правило, срабатывающее > 5% и не коррелирующее с судьёй, переводится в
  `warning`; удаление — отдельным PR.

**W5 сделано (2026-10-24):**

- `scripts/backtest_lint.py` — read-only прогон закрытого набора правил по JSONL
  выгрузке `dialog_turns.payload` (тот же экспорт, что у structure-fidelity);
  отчёт `rule → findings / documents_hit / share / by_kind` в stdout и
  `artifacts/lint_backtest.json`. Ни БД-записи, ни LLM; находки не несут прозы
  (`LintFinding`), поэтому отчёт безопасно приложить к тикету.
- `tests/fixtures/lint/legit_answers.jsonl` — 13 курируемых легитимных документов
  (защитные кейсы: `1.`-ячейки таблицы, `[1]`/`[2]` при `source_refs`, `[2024]`,
  `##`/`mcp:` внутри code, `>` в середине фразы, честно пустой документ, widget
  с absolute http(s)). Golden-набор — единственное место, где срабатывание = FP;
  `tests/unit/test_lint_backtest.py` держит его на нуле (unit-гейт).
- Разбивка по осям — `meta.kind` (персистится). `response_shape` — ось Intent'а,
  в payload её нет: джойнить нечем, выдуманная ось была бы хуже отсутствующей.
- Триггер `> 5%` реализован как строгое неравенство (`high_share_rules`);
  корреляция с `palatium_judge_score` остаётся ручным шагом — в корпусе нет
  judge-скоров, автоматический джой выдал бы непроверенное утверждение за факт (086).


### W6 — Промпты и граница «инструкции vs данные» — реализовано

- 3–5 примеров на `response_shape` в `<examples>`: эталон, граничный (пустой
  документ/отказ), контрпример в позитивной формулировке.
- `prompts.py` остаётся статической константой (030): примеры — часть текста, не
  динамическая сборка.
- Граница уже существует: `<formatter_input>` + JSON + fences
  `<<<UNTRUSTED_TOOL_OUTPUT>>>`. **Второй wrapper `<document>` не вводим** — это
  дубль границы; задача — не интерполировать пользовательский текст в
  `<instructions>` и покрыть тестом prompt injection (`core/security/prompt_injection.py`).
- Цена: примеры увеличивают prompt-токены; бюджет completion (8k) не защищает
  prompt. Замер до/после — в том же PR.

**W6 сделано (2026-10-24):**

- `## EXAMPLES` в обоих промптах: `comparison_table`, `plan`, `prose` и граничный
  `boundary_no_source_text` (честная формулировка вместо выдуманного ответа).
  Примеры — данные (`SCHEMA_SHAPE_EXAMPLES` / `MARKDOWN_SHAPE_EXAMPLES`), текст
  промпта собирается при импорте: константа остаётся статической (030).
- Контрпример сформулирован позитивно: «сравнение — всегда таблица; списки несут
  рекомендации, а не сравниваемые признаки» (в обоих промптах).
- `tests/unit/test_formatter_prompt_examples.py` валидирует каждый JSON-пример через
  `ContentDocument`, каждый markdown-пример — через настоящий парсер; форма примера
  (table/steps/paragraphs) закреплена отдельно.
- Цена измерена и закреплена: schema 1471 → 1771 токен (+20 %), legacy 1740 → 1877
  (+8 %); потолки — 1900 токенов (тест) и 7900 символов (пере-базированный гейт в
  `test_formatter_action_contract.py`); примеры ≤ 25 % промпта.
- `tests/unit/test_formatter_prompt_boundary.py`: единственный плейсхолдер в
  системных промптах — литерал `{JSON}`; текст хода и вложения — только внутри
  `<formatter_input>`; fence сохраняется; инъекции из корпуса (en/ru override,
  fence breakout, role hijack) флагаются сканером.
- **Найдено и закреплено тестом:** сканер обязан работать по сырому тексту до
  JSON-сериализации — `\nIgnore` превращается в `nIgnore`, и `\b`-якоря правил
  теряют границу. Сканирование собранного конверта недосчитывает и флагает
  собственный fence как `fence_breakout`.
- **Не сделано осознанно:** второй wrapper `<document>` (дубль границы, 050);
  автоматического гейта «модель соблюдает форму» нет — это eval/nightly, не unit.


### W7 — R&D: краткость и ревизия

**W7a — бюджет длины (сделано).** `meta.verbosity_budget: Literal["minimal","standard",
"detailed"] = "standard"`, аддитивно (persisted-документы и кэш читаются, `schema_version`
не бампается). Владелец оси — сервер, а не модель: поле помечено `SkipJsonSchema`, потому
что в strict-схеме провайдера any listed field становится обязательным, и модель начала бы
выдумывать собственный бюджет. `domain/policies/verbosity.py`
(`VerbosityPolicy.for_transformation`) выводит его из оси `transformation`
(`shorten → minimal`, `expand → detailed`, остальное → `standard`); значение проставляет
`align_formatter_meta` (общая граница LLM/fast-path/fallback), payload получает то же
значение из той же политики. Оба промпта — статическая секция `## LENGTH BUDGET`;
краткость не отменяет ограничения, цитаты и предупреждения, правила формы сильнее бюджета.
Цена: schema 1771 → 1866 токенов, legacy 1877 → 1972 (потолки 1900/2000, 8 300 символов).
`tests/unit/test_verbosity_budget.py`.

**W7b — `revision_of` (сделано, отрисовка — W7b-UI).** Diff считается сервером на границе persist
(`intent_graph_runner`, `intent_hitl_flow`), где предыдущий `ContentDocument` уже под рукой
в `dialog_window`: Formatter не получает зависимость от хранилища (000), лишнего чтения БД
нет. Идентичность — **content-hash**, а не id от модели: `domain/content/revision.py`
(`block_content_hash`, `document_content_hash`, `document_revision`). Хеш блока — sha256
канонического JSON (64 бита, стабилен между позициями и ходами); хеш документа — locale +
title + blocks (128 бит) и **не** включает `confidence`/`citations`/`verbosity_budget`,
иначе пере-рендер того же текста выглядел бы ревизией.

`DocumentRevision` (`revision_of`, `changed_blocks`, `changed_block_indices`,
`removed_blocks`, `unchanged_blocks`) — мультимножество, а не множество: удаление одной из
двух идентичных реплик — реальное удаление, перемещение блока — не изменение. Пишется в
payload хода как `revision` и только когда ревизия действительно есть:
`RevisionPolicy.continues_prior_document` (есть `revision_feedback` или
`transformation ≠ none`) + читаемый предыдущий ответ + содержимое изменилось; решение и
расчёт собраны в одном входе `turn_revision`, чтобы persist и живой кадр не разошлись.
Синтезированная HITL-карточка «Tool approval required» ревизией не считается.
Сломанный/легаси payload предыдущего хода — отсутствующая база diff, а не сбой хода (035).
`tests/unit/test_document_revision.py`.

**W7b-UI — отрисовка (сделано 2026-10-24).** `RevisionNote` + разметка
`BlockRenderer` по `changed_block_indices`: позиции приходят с сервера, потому что
пересчёт content-hash на клиенте был бы второй реализацией контракта идентичности и
ломался бы молча. Живой оборот получает diff в кадре `result`
(`stream_result_frame`, `onRevision`), hydrate — из payload хода. Удалённые блоки —
только числом (их в документе уже нет). HITL-resume отдаёт документ **с** конвертом
`revision` (`HitlRespondResponse.revision`): тот же `turn_revision` на границе persist,
`FinalizedTurn` в application-слое, `HitlResolvedEvent.revision` на клиенте — иначе
замена документа по `resumed` теряла разметку до перезагрузки.
`web/tests/unit/revision-note.test.tsx`, `web/tests/unit/hitl-resolved-revision.test.tsx`,
`web/tests/integration/process-stream-typed.test.ts`.

## 6. Порядок и зависимости

| Волна | Зависит от | Гейт |
|---|---|---|
| W0a lint | — | unit-тесты правил, метрика findings — **сделано** |
| W0b метрики | W0a | дашборд с раздельными знаменателями — **сделано** |
| W1 стратегия показа | W0b (наблюдаемость) | `layout_shift_count == 0` не растёт; `palatium_sse_first_block_seconds` p95; TTFVF ≤ 300 мс (E2E `ttfvf.spec.ts`) — **сделано** |
| W2 a11y | W1 (закрытые блоки) | Playwright+axe, ручной VoiceOver/NVDA — **сделано** (разметка и правила; ручной чек-лист `web/e2e/a11y-announcements.manual.md`) |
| W3a цитаты (модель) | adapter citations | resolution rate, ноль висячих — **сделано** |
| W3b просмотрщик | W3a + новая спека | клик ведёт к подсветке либо честно «недоступно» — **сделано** (часть 1: якоря в контракте + панель цитат; часть 2: `SourcePanel` + `citation-locate`, спека `docs/source-citation-highlight.md`) |
| W4 decomposed judge | W0b | 4 спана, калибровка на golden set — **сделано** (opt-in per task; tier судьи и «10–20%» — вне волны) |
| W5 backtesting | W0a + корпус | отчёт по правилам, ≥10 защитных кейсов — **сделано** (13 кейсов; FP-гейт на golden, доля на корпусе — отчёт) |
| W6 few-shot | — | prompt-injection тест, замер токенов — **сделано** (4 формы × 2 пути; +20 %/+8 %, потолки закреплены; граница «инструкции vs данные» под тестом) |
| W7 R&D | W1–W4 | W7a: ось бюджета с одним владельцем, замер цены — **сделано**; W7b: diff по content-hash на границе persist, без id от модели — **сделано** (UI: `RevisionNote` + индексы блоков, живой `result.revision`, HITL-resume конверт) |

Исходные «недели 1–8» не используются: W3b и W5 упираются в отсутствующие
предусловия (просмотрщик, корпус), а W4 — в норму 040.

## 7. Enforcement

- Новые имена метрик — только через `core/observability/metrics.py` (040).
- `StreamDisplay`, `LintSeverity`, `CitationAnchor` — по одному Literal, без
  локальных дублей (010/055).
- Линтер не переписывает документ; правки контента остаются в существующем
  repair-пути (одна ответственность).
- Автоматического гейта «судья согласован» и «FP ≤ 1%» нет — это отчёт и ревью
  (086: не выдавать ручную проверку за CI). Единственное исключение — курируемый
  golden-набор W5 (`tests/fixtures/lint/legit_answers.jsonl`): на размеченных
  легитимных ответах срабатывание и есть FP, поэтому «ноль» там проверяется
  unit-тестом, а не глазами.

## 8. Открытые вопросы

1. Есть ли в LiteLLM-конфиге провайдер, реально отдающий citations через
   `response.choices[0].message.annotations`? Адаптер теперь пробрасывает оба
   формата (`url_citation`, Anthropic `*_location`), но пока ни один путь не шлёт
   провайдеру цитируемые документы — metric будет 0 до подключения такого вызова
   (это осознанно: пайплайн W3a — «не терять данные», а не «выдумать цитаты»).
2. Кто владелец экрана просмотра источника (W3b): новый роут или модалка поверх
   `read_attachment`?
3. Корпус для W5: сколько ходов с persisted `ContentDocument` доступно и какой
   retention у `dialog_turns`? Скрипт готов и работает на экспорте, но доля
   срабатываний на реальном трафике неизвестна, пока выгрузка не прогнана — это
   единственный шаг W5, который нельзя сделать без доступа к прод-данным.
4. Судья на PII: внутренняя модель или `requires_review` без судьи?

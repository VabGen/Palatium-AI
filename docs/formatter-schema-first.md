# Formatter: schema-first contract (canary rollout)

**Статус:** Фаза 1–2 в коде, Фаза 3 (canary) включена на staging.
**Дата:** 2026-10-16.

Два контракта генерации `ContentDocument`, выбираемые `FORMATTER_MODE`:

| Контракт | Как получается документ | Путь удаления |
|---|---|---|
| `legacy` | GFM Markdown → `markdown_parser.py` + repair-loop | Фаза 4 |
| `schema_first` | провайдеру отдаётся `response_format=json_schema` от `ContentDocument` | целевой |

`schema_first` не парсит Markdown регулярками: модель заполняет типизированный
`schema` (`strict: true`), результат валидируется тем же pydantic-классом.

## Ключи конфигурации (two-key, как `ADAPTIVE_GROUNDING_*`)

| Ключ | Смысл |
|---|---|
| `FORMATTER_MODE` | `legacy` (kill switch) или `schema_first` (целевой контракт) |
| `FORMATTER_ROLLOUT_PCT` | покрытие `schema_first`: `0` off, `1..99` sticky-canary, `100` полный cutover |

`FORMATTER_MODE=schema_first` **сам по себе не переключает всех**: при `PCT=0` работает
legacy и пишется warning `formatter.rollout.zero_coverage`. Так одиночная правка
`MODE` не становится footgun'ом (та же логика, что `warn_if_enabled_but_zero_rollout`).

Резолв — чистая функция `resolve_formatter_mode` (`core/observability/formatter_rollout.py`),
когорта sticky по `hash8(user_id) % 100`. Один процесс обслуживает обе когорты
детерминированно: rolling update не переключает контракт пользователя на середине диалога.

## Canary на staging

`env/.env.staging(.example)`: `FORMATTER_MODE=schema_first`, `FORMATTER_ROLLOUT_PCT=5`.
Рампа без деплоя: `5 → 25 → 50 → 100`.

**Rollback — один ключ:** `FORMATTER_ROLLOUT_PCT=0` (оставить `MODE=schema_first`, чтобы
вернуть рампу одной правкой). Полный откат: `FORMATTER_MODE=legacy`.

## Метрики сравнения (Прометей, единый реестр 040)

Латентность по когорте — `palatium_agent_request_duration_seconds` с
`node_name="formatter:legacy"` / `"formatter:schema_first"` (mode-split, обе когорты
в одном процессе). Исходы генерации живут **не здесь**, а в отдельном счётчике —
одна метрика владеет одним фактом (050):

| Метрика | Значения |
|---|---|
| `palatium_formatter_schema_total{path,outcome}` | `path`: `schema_first` / `legacy_markdown`; `outcome`: `valid`, `invalid`, `empty_blocks`, `unsupported`, `fallback` |
| `palatium_agent_errors_total{error_type}` | `schema_first_llm_stage_failure`, `llm_stage_failure` — транспорт/таймаут |
| `palatium_content_lint_findings_total{rule,severity}` | дефекты, валидные по схеме, но неверные для пользователя |
| `palatium_citation_resolution_total{anchor,outcome}` | якоря провайдера: знаменатель — всё, что он прислал (W3a) |
| `palatium_citation_highlight_total{outcome}` | открытия места цитаты: `declared_range` / `quote_match` / `ambiguous_quote` / `quote_not_found` / `no_text` (W3b-2) |

`formatter`, `emit:*` остались в `node_name` только как латентность и пути
деградации (`emit:llm`, `emit:fallback_after_parse_errors`,
`emit:fallback_deterministic`).

**Schema validity rate** — доля попыток `schema_first`, где JSON прошёл схему:

```promql
sum(rate(palatium_formatter_schema_total{path="schema_first",outcome="valid"}[30m]))
/
sum(rate(palatium_formatter_schema_total{path="schema_first",outcome=~"valid|invalid"}[30m]))
```

Из знаменателя **исключены** осознанно:

- `unsupported` — провайдер отказал в `stream` + `json_schema`, вердикта по схеме нет;
- `empty_blocks` — документ схему прошёл, но модель выбросила содержимое: это
  дефект контента, а не схемы, и он не должен растворять сигнал промпта/модели;
- транспортные ошибки — их владелец `palatium_agent_errors_total`.

```promql
# p95 latency schema_first против legacy
histogram_quantile(0.95, sum by (le) (rate(palatium_agent_request_duration_seconds_bucket{agent_type="formatter",node_name="formatter:schema_first"}[1h])))
/
histogram_quantile(0.95, sum by (le) (rate(palatium_agent_request_duration_seconds_bucket{agent_type="formatter",node_name="formatter:legacy"}[1h])))
```

## Триггеры отката

| Триггер | Действие |
|---|---|
| schema validity rate < 0.995 за 30 мин (`path="schema_first"`) | `PCT=0`, разобрать провайдера/схему |
| `outcome="empty_blocks"` > 1% попыток | `PCT=0`, разобрать промпт/схему (`required` на `blocks`) |
| `outcome="unsupported"` > 0.5% | `PCT=0`, разобрать провайдера |
| p95(schema_first) / p95(legacy) > 1.2 | пауза рампы |
| format-регрессии (иконки, списки, формальность) | `PCT=0` |

Fallback спроектирован как degraded-graceful: при отказе провайдера, невалидном JSON или
пустом `blocks` на непустом ответе вызов переоткрывает legacy-путь, а не теряет ответ.

## Детерминированный lint (W0a)

Документ, валидный по Pydantic, ещё не обязательно корректен для пользователя.
`domain/content/lint/` проверяет пять классов дефектов на каждом ходе Formatter'а
(оба контракта и fallback):

| Правило | Что ловит |
|---|---|
| `internal_marker_leak` | внутренний ключ, `[[page N]]`, `mcp:<server>.<tool>` в прозе |
| `dangling_citation` | `[n]` без соответствующего `meta.source_refs` |
| `duplicate_prose` | два соседних блока с одинаковым текстом |
| `markdown_residue` | `#`, `|`, `- `, `>` в начале plain-text блока |
| `empty_section` | заголовок без тела |

Линтер **не переписывает** документ: правки остаются в repair-пути Formatter'а.
Форма ответа не проверяется — её владелец `ShapeRecipePolicy`. Сигнал —
`palatium_content_lint_findings_total{rule, severity}` плюс структурированный лог
без прозы. План и открытые волны — `.cursor/plans/answer-quality-max-pro.md`.

## Backtesting правил lint (W5)

Правило, написанное по одному случаю, точно на нём и неизвестно насколько шумно на
реальном трафике. `scripts/backtest_lint.py` прогоняет закрытый набор правил по
выгрузке `dialog_turns.payload` — read-only, без LLM и без записи в БД:

```powershell
uv run python scripts/backtest_lint.py --turns $env:TEMP\assistant_turns.jsonl
```

| Флаг | Смысл |
|---|---|
| `--turns` | JSONL выгрузка assistant-payload'ов (та же, что у structure-fidelity); корпус содержит PII и в репозиторий не попадает (`artifacts/` в `.gitignore`) |
| `--golden` | `tests/fixtures/lint/legit_answers.jsonl` — курируемый набор легитимных ответов |
| `--json` | отчёт `artifacts/lint_backtest.json`: `rule → findings / documents_hit / share / by_kind` |
| `--threshold` | доля ответов, выше которой правило уходит в review (по умолчанию 5 %) |

Доля срабатываний на прод-корпусе **не** является false-positive rate: разметки у
корпуса нет, «правило сработало» не значит «ответ был плохим». FP честно считается
только на golden-наборе, и там он равен нулю — это unit-гейт
(`tests/unit/test_lint_backtest.py`), а доля на корпусе — отчёт для ревью (086).

Разбивка отчёта идёт по `meta.kind` — единственной персистируемой оси ответа.
`response_shape` принадлежит Intent'у и в payload не сохраняется, поэтому джойнить
нечем: добавление её в payload — отдельная задача, а не молчаливая подмена оси.

Правило с долей выше порога — кандидат на `warning`. Решение принимает человек:
корреляция с `palatium_judge_score` автоматически не считается (086 — ручную проверку
не выдаём за CI), удаление правила — отдельным PR.

## Few-shot по форме ответа и граница «инструкции vs данные» (W6)

Форму задаёт не только текст правила, но и пример: модель копирует структуру, которую
видит. В оба промпта (`FORMATTER_SCHEMA_PROMPT` и `FORMATTER_SYSTEM_PROMPT`) добавлен
блок `## EXAMPLES` — по одному примеру на форму, которая чаще всего ломается:

| Пример | Что закрепляет |
|---|---|
| `comparison_table` | сравнение — таблица с колонкой признаков, а не список |
| `plan` | `steps` с двумя и более действенными шагами |
| `prose` | только абзацы, без заголовков и списков |
| `boundary_no_source_text` | честная формулировка «текст не извлекается» вместо выдуманного ответа |

Примеры — **данные, а не проза внутри строки**: `SCHEMA_SHAPE_EXAMPLES` и
`MARKDOWN_SHAPE_EXAMPLES` в `prompts.py`, текст промпта собирается из них при импорте
(промпт остаётся статической константой, 030). `tests/unit/test_formatter_prompt_examples.py`
проверяет каждый JSON-пример через `ContentDocument.model_validate`, а каждый markdown-
пример — через настоящий парсер: пример, который не проходит контракт, учил бы модели
именно той ошибке, которую должен предотвращать.

Цена примеров — измеряется и закреплена, потому что платится на каждом ходе
(`count_tokens`, оценка):

| Промпт | До | После | Прирост |
|---|---|---|---|
| `FORMATTER_SCHEMA_PROMPT` | 1471 токен | 1771 | +20 % |
| `FORMATTER_SYSTEM_PROMPT` | 1740 токенов | 1877 | +8 % |

Потолки: 1900 токенов для schema-пути (тест), 8 300 символов для legacy-пути
(`test_formatter_action_contract.py` — пере-базирован с «60 % от 11 625-символьного
монолита» на сегодняшний размер +5 %; смысл гейта сохранён, молчаливый рост — нет).
Примеры занимают ≤ 25 % промпта: доминирующий few-shot перестаёт читать правила.

### Граница «инструкции vs данные»

Она уже была и остаётся прежней — второй wrapper `<document>` не вводится, это дубль
существующей границы (050):

- системные промпты — константы; единственный `{…}`-плейсхолдер в них — литерал
  `{JSON}` из описания конверта (тест: любой `{user_text}`-подобный плейсхолдер падает);
- текст хода, вложения и история диалога приходят только внутри
  `<formatter_input>{JSON}</formatter_input>`;
- вложения остаются в `<<<UNTRUSTED_TOOL_OUTPUT>>>…<<<END_UNTRUSTED_TOOL_OUTPUT>>>`.

Сканер инъекций (`core/security/prompt_injection.py`) работает по **сырому**
недоверенному тексту — до сериализации в JSON. Порядок обязателен: JSON-экранирование
превращает `\nIgnore` в `nIgnore`, оба символа словесные, и `\b`-якорь любого правила
теряет границу; сканирование уже собранного конверта дало бы недосчёт и, вдобавок,
флагало бы собственный терминатор fence как `fence_breakout`
(`tests/unit/test_formatter_prompt_boundary.py`).

## Бюджет длины ответа (W7)

`meta.verbosity_budget` (`minimal` / `standard` / `detailed`) — ось длины хода, и у неё
один владелец: **сервер**. Пользователь просит краткость словами («сократи»,
«подробнее»), единственный классифицированный сигнал — ось `transformation`, поэтому
`domain/policies/verbosity.py` (`VerbosityPolicy.for_transformation`) выводит бюджет:
`shorten → minimal`, `expand → detailed`, остальное (`rewrite`, `restructure`, `none`) →
`standard`.

Почему не поле модели: `DocumentMeta` входит в strict-схему провайдера, а поле там
становится **обязательным** — модель начала бы выдумывать бюджет и тем самым размечать
себя сама. Поэтому поле помечено `SkipJsonSchema` (как `citations`): оно есть в контракте
для клиента, но не в схеме генерации. Значение проставляет `align_formatter_meta` —
общая граница LLM-, fast-path- и детерминированного путей, — а payload получает то же
значение из той же политики (тест сверяет их равенство).

- Поле аддитивное с дефолтом `standard`: persisted-документы и кэш читаются без
  `schema_version`-бампа.
- Оба промпта получают статическую секцию `## LENGTH BUDGET` (правила длины, а не
  подстановка значения): бюджет — вход, инструкция — константа (030).
- Краткость не отменяет ограничения, цитаты и предупреждения; правила формы сильнее
  бюджета — сравнение остаётся таблицей при любом бюджете.
- Цена: schema-промпт 1771 → 1866 токенов, legacy 1877 → 1972 (потолки 1900/2000 и
  8 300 символов). Рост закреплён тестами, а не «замечен на глаз».

## Ревизия ответа: diff по content-hash (W7b)

Ревизия — это не «второй канал замечаний» (`revision_feedback`), а идентичность
документа: ответ, который переделывает предыдущий. `RevisionPolicy` говорит «да» только
по двум серверным сигналам — есть `revision_feedback` (ответ был отклонён) или
`transformation ≠ none` (restructure/expand/shorten/rewrite берут предыдущий ответ как
источник). Вопрос, который лишь *ссылается* на прошлый ответ, — новый документ: diff к
нему никто не просил.

Идентичность блоков — **хеш содержимого**, а не id от модели: придуманный моделью `b3`
подсветил бы не тот абзац. `domain/content/revision.py`:

| Функция | Что даёт |
|---|---|
| `block_content_hash` | sha256 канонического JSON блока, 64 бита; стабилен между позициями |
| `document_content_hash` | 128 бит по locale + title + blocks; **без** `confidence`/`citations`/`verbosity_budget` |
| `document_revision` | `revision_of`, `changed_blocks`, `changed_block_indices`, `removed_blocks`, `unchanged_blocks` |

Мультимножество, а не множество: удаление одной из двух одинаковых реплик — реальное
удаление, перемещение блока — не изменение (идентичность = содержимое, не позиция).

Где считается: один вход — `turn_revision` (`intent_turn_helpers.py`): он же применяет
`RevisionPolicy`, чтобы persist и живой кадр не разошлись в трактовке «это ревизия?».
Предикат — `dialog_window` уже в руках, Formatter не получает зависимость от хранилища,
лишнего чтения БД нет. Результат пишется в payload ассистентского хода ключом
`revision` и только когда ревизия действительно есть (сигнал + читаемая база + содержимое
изменилось). Синтезированная карточка «Tool approval required» ревизией не считается;
сломанный/легаси payload предыдущего хода — отсутствующая база diff, не сбой хода (035).

Отрисовка (W7b-UI, `RevisionNote` + `BlockRenderer`):

- `changed_block_indices` — позиции изменённых блоков в **текущем** документе. Клиент
  не пересчитывает content-hash: вторая реализация канонизации в TypeScript разошлась бы
  молча (float, новое поле), и подсветка просто исчезла бы — тихий отказ вместо ошибки.
  Старый payload без индексов показывает счётчики без разметки, а не «примерно».
- `removed_blocks` — только число: удалённого блока в документе уже нет, показывать нечего.
- Живой оборот получает тот же diff в кадре `result` (`stream_result_frame`), поэтому
  ревизия видна без перезагрузки. HITL-resume отдаёт документ **вместе** с конвертом
  `revision` (`HitlRespondResponse.revision`, `HitlResolvedEvent.revision`): иначе замена
  документа по `resumed` теряла разметку до перезагрузки хода. Источник один —
  `turn_revision` на границе persist; офф-граф мутации (`doc-ingest-`, `mem-save-`, …)
  дают новое одно-блочное сообщение и `revision: null`.

## Стратегия отображения по блокам (W1)

Стримится не «всё, что пришло», а только то, где префикс уже читается как ответ.
Решение — доменная политика `domain/policies/stream_display.py`
(`StreamDisplayPolicy.strategy_for`), единственный владелец матрицы; сканер
`partial_document.py` спрашивает её, клиент рендерит по тому же ответу.

| Стратегия | Блоки | Почему |
|---|---|---|
| `text_delta` | `paragraph` | префикс — предложение в процессе, читать его полезно |
| `skeleton` | `list`, `steps`, `table`, `kv`, `chart` | смысл элемента — набор строк: одна строка читается как ответ |
| `on_close` | `heading`, `callout`, `code`, `formula`, `divider`, `widget` | обрывок кода/формулы — дезинформация; короткое нечего стримить |

Неизвестный тип → `on_close` (fail-safe). Проза открытого абзаца отдаётся
append-only фрагментами; `safe_cut` придерживает хвост, который может оказаться
половиной внутреннего маркера (020), а закрывающий фрейм досылает остаток из
**валидированного** блока, поэтому «нарисованный префикс + остаток» всегда равно
`block.text` (правило superset: `layout_shift_count == 0`). Незавершённый escape
(`\u00` → `\u00e9`) и одиночный суррогат не рисуются вовсе.

Время до первого типизированного блока — отдельная метрика:

```promql
histogram_quantile(0.95, sum by (le) (rate(palatium_sse_first_block_seconds_bucket[30m])))
```

Она не заменяет `palatium_sse_ttft_seconds` (первый видимый фрейм, включая прозу):
регресс «прозу стримим, блоки залипли» виден только здесь.

## Границы

- Удаление legacy (`markdown_parser.py`, `icon_sanitizer.py`, repair-слой, Markdown-промпты) —
  **Фаза 4**, после 99%+ `schema_first`. До этого legacy остаётся fallback'ом и не расширяется.
- `strict: true` держится на нормализации схемы в `domain/llm/structured_output.py`
  (`strict_json_schema`): без неё провайдер игнорирует дефолтные поля (например, `blocks`).

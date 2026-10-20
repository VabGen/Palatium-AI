# SSE streaming

Актуально на 2026-10-19. Транспорт — `StreamingResponse` в
`presentation/api/routers/intents.py`, не `sse-starlette`. Кадр:

```text
event: {name}
data: {json.dumps(payload)}

```

`data` — один JSON-объект. Перевод строки внутри строки `delta`/`content`
закодирован JSON и не является границей события.

Канон Hybrid: `.cursor/plans/evolution-to-big-tech.md` (Phase 1).

## События, которые доходят до клиента

| Событие | Кто эмитит | Полезная нагрузка | Клиент (React) |
|---|---|---|---|
| `hop` | `IntentGraphRunner` | `{node, task_id, thread_id}` | `onHop` (имя события зафиксировано) |
| `document_title` | Formatter (`schema_first`) | `{title}` | typed preview: заголовок известен до первого блока; prose-fallback подавляется |
| `block_delta` | Formatter (`schema_first`) | `{index, block}` | **typed preview**: закрытый блок → `BlockRenderer` (append-only, без `replace`) |
| `answer_delta` | workers / fast-path / dual от Formatter / закрытый блок streamed-документа | `{delta, replace?}` | fallback preview; TTFT metric |
| `text_delta` | `FormatterMarkdownEmitter` | `{content}` | **primary** stream preview (GFM; keeps `<icon name="…"/>` for FE `TokenIcon`, no emoji) |
| `result` | `IntentService.process_stream` | `{task_id, thread_id, result: FormatterTaskResult}` | финальный `ContentDocument` |
| `done` | роутер `intents.py` | `{}` | не используется |
| `error` | `process_stream` или роутер | `{message, …}` либо `{detail, status_code}` | исключение на клиенте |

`final_state` и `_values` остаются внутри графа и в SSE не попадают.

## Один writer на turn

`ANSWER_WRITER_MODE` + `ANSWER_WRITER_ROLLOUT_PCT` (sticky по `thread_id`) выбирают
единственного автора ответа:

- `worker` — Researcher пишет финальный GFM, Formatter рендерит его
  детерминированно (`markdown_to_content_document`), без LLM. LLM-fallback — только
  при 0 блоков, truncation-маркере, locale mismatch или запросе на композицию;
- `formatter` — Formatter единственный writer (restructure, clarify/choice, verbatim,
  revision), черновик worker'а в клиент не уходит: 8-секундный fallback-stream
  отключён, иначе его заменил бы собственный ответ Formatter'а.

Rollback — `ANSWER_WRITER_ROLLOUT_PCT=0` (при `MODE=worker`).

## Ход без ошибки

1. `hop` — узел графа отдал update.
2. `answer_delta` — готовая prose работника (и позже замена черновика с `replace`).
   Первый user-visible чанк пишет `palatium_sse_ttft_seconds`. При явной
   `response_shape != auto` черновик не красится: финальная композиция гарантированно
   другая, и замена была бы тем самым layout shift (ADR 0005).
3. `text_delta` — токены GFM от Formatter (включая `<icon name="…"/>`; незакрытый
   хвост тега держится между чанками). На первом чанке после worker draft —
   dual `answer_delta` с `replace: true` **один раз**; клиент не сбрасывает
   `textAccumulated`, если `text_delta` уже шёл. Далее dual без `replace`.
4. `result` — `FormatterTaskResult`; `ContentDocument` собран
   `markdown_to_content_document` из финального markdown (JSON ContentDocument —
   fallback совместимости).
5. `done` — поток закрыт. При обрыве клиента `done` не шлётся.

HITL: кликабельные карточки только из серверного `result` / minted cards.
XML-теги `<hitl-action>` / `<hitl-choice>` в стриме — не интерактивны на клиенте
(парсятся на сервере после стрима).

## Контракт стриминга на turn

Ось объявлена один раз — `StreamingContract` (`domain/policies/types.py`), живёт
на `TurnSseBridge.stream_contract`. Turn выбирает ровно один контракт; узлы спрашивают
бридж, а не собственный флаг (055: одно решение, не дублировать по узлам).

| Контракт | Когда | Что видит пользователь |
|---|---|---|
| `legacy_markdown` | `FORMATTER_MODE=legacy` (или rollout не дал `schema_first`) | worker draft → **один** `replace` на первом `text_delta` Formatter'а |
| `structured_incremental` | эффективный `schema_first` | ничего во время worker'ов (typing indicator) → типизированные блоки документа (`block_delta`), append-only; `answer_delta` — fallback для старых клиентов |
| `buffered` | нет превью вообще | только финальный `result` |

**Инвариант `structured_incremental`:** `replace` не отправляется ни разу.
Провайдер стримит `json_schema`-документ, `PartialDocumentScanner`
(`application/agents/formatter/partial_document.py`) отдаёт на каждый закрытый
элемент `blocks[]` **два** кадра из одного парса:

- `block_delta {index, block}` — блок, провалидированный против `ContentBlock`
  (включая межполевые инварианты `validate_content_block`: ширина строк таблицы,
  длина серий графика, которые не выразить в JSON Schema). Клиент рисует его тем
  же `BlockRenderer`, что и финальный документ;
- `answer_delta {delta}` — prose того же блока для клиентов, которые ещё не знают
  `block_delta` (dual-emit, как `text_delta`/`answer_delta` в Phase 1).

Заголовок документа — отдельный `document_title` **до** первого блока: заголовок не
является блоком, и если нарисовать его prose-кадром, переход на типизированное
превью сдвинет текст. Финальный `ContentDocument` — надмножество уже показанных
блоков. Поэтому промежуточный worker draft **не** красится: заменять его нечем
(`_emit_worker_answer_deltas` / formatter-node гасят превью через
`structured_preview_active()`), иначе черновик навсегда остался бы над ответом.

Provider без поддержки `stream` + `json_schema` → `StructuredOutputUnsupportedError`
→ legacy-путь; если часть блоков уже показана, legacy делает тот самый один `replace`.

## Fast path

`FormatterFastPathPolicy` пропускает LLM для prose без структуры
(`plain_paragraph_count` не `None`) и не длиннее `FORMATTER_PASSTHROUGH_MAX_CHARS`,
плюс уверенный worker, совпадение локали и отсутствие review / revision /
restructure / choice / явной `response_shape`.
Заголовки, списки и fenced-блоки остаются на LLM независимо от длины.
Исключение: capability `verbatim_extraction` — passthrough без лимита 600 и без
требования «plain prose» (тело worker = ответ; LLM не переписывает уже
показанный SSE draft).

## Новым агентам

- Стриминг определяется контрактом turn'а (`StreamingContract`), не флагом узла.
  Терминальный узел, который сам формирует документ, красит его инкрементально;
  промежуточный worker под `structured_incremental` молчит.
- Early prose — `emit_answer_deltas` (с dedup по уже показанному).
- Типизированный блок streamed-документа — `emit_document_block` (`block_delta`,
  append-only, `index` = позиция в `blocks[]`; payload уже прошёл
  `sanitize_block`, code/formula не переписываются).
- Заголовок streamed-документа — `emit_document_title` (один кадр до первого блока).
- Prose streamed-документа — `emit_structured_answer_delta` (append-only, без
  `replace`, без dedup: повтор абзаца в документе легитимен; fallback, не primary).
- Formatter markdown tokens — только через `FormatterMarkdownEmitter` (`text_delta` + dual).

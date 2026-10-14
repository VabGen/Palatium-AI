# SSE streaming

Актуально на 2026-10-13. Транспорт — `StreamingResponse` в
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
| `answer_delta` | workers / fast-path / dual от Formatter | `{delta, replace?}` | fallback preview; TTFT metric |
| `text_delta` | `FormatterMarkdownEmitter` | `{content}` | **primary** stream preview (GFM; keeps `<icon name="…"/>` for FE `TokenIcon`, no emoji) |
| `result` | `IntentService.process_stream` | `{task_id, thread_id, result: FormatterTaskResult}` | финальный `ContentDocument` |
| `done` | роутер `intents.py` | `{}` | не используется |
| `error` | `process_stream` или роутер | `{message, …}` либо `{detail, status_code}` | исключение на клиенте |

`final_state` и `_values` остаются внутри графа и в SSE не попадают.

Deprecated: `formatter_delta` (debug JSON tokens) — больше не эмитится; Formatter
стримит `text` + `text_delta`.

## Ход без ошибки

1. `hop` — узел графа отдал update.
2. `answer_delta` — готовая prose работника (и позже замена черновика с `replace`).
   Первый user-visible чанк пишет `palatium_sse_ttft_seconds`.
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

## Fast path

`FormatterFastPathPolicy` пропускает LLM для prose без структуры
(`plain_paragraph_count` не `None`) и не длиннее `FORMATTER_PASSTHROUGH_MAX_CHARS`,
плюс уверенный worker, совпадение локали и отсутствие review / revision / restructure / choice.
Заголовки, списки и fenced-блоки остаются на LLM независимо от длины.
Исключение: capability `verbatim_extraction` — passthrough без лимита 600 и без
требования «plain prose» (тело worker = ответ; LLM не переписывает уже
показанный SSE draft).

## Новым агентам

- Структурированный `ContentDocument` не стримить чанками. Он появляется в `result`.
- Early prose — `emit_answer_deltas`.
- Formatter markdown tokens — только через `FormatterMarkdownEmitter` (`text_delta` + dual).

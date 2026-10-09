# SSE streaming

Актуально на 2026-10-09. Транспорт — `StreamingResponse` в
`presentation/api/routers/intents.py`, не `sse-starlette`. Кадр:

```text
event: {name}
data: {json.dumps(payload)}

```

`data` — один JSON-объект. Перевод строки внутри строки `delta` закодирован
JSON и не является границей события.

## События, которые доходят до клиента

| Событие | Кто эмитит | Полезная нагрузка | Клиент (React) |
|---|---|---|---|
| `hop` | `IntentGraphRunner` | `{node, task_id, thread_id}` | `onHop` |
| `answer_delta` | `emit_answer_deltas` | `{delta, replace?}` | `onAnswerDelta`; `replace: true` сбрасывает аккумулятор |
| `formatter_delta` | `FormatterAgent`, только если `FORMATTER_DEBUG_STREAM_DELTAS=true` | `{delta}` — сырые JSON-токены | `onFormatterDelta`, и только пока не было `answer_delta` |
| `result` | `IntentService.process_stream` | `{task_id, thread_id, result: FormatterTaskResult}` | финальный документ |
| `done` | роутер `intents.py` | `{}` | не используется |
| `error` | `process_stream` или роутер | `{message, task_id, thread_id}` либо `{detail, status_code}` | исключение на клиенте |

`final_state` и `_values` остаются внутри графа и в SSE не попадают.

## Ход без ошибки

1. `hop` — узел графа отдал update.
2. `answer_delta` — готовая plain-prose работника (и позже замена того же черновика с `replace`). Первый такой чанк пишет `palatium_sse_ttft_seconds`.
3. `formatter_delta` — только при включённом debug-флаге.
4. `result` — `FormatterTaskResult`, внутри него `ContentDocument`.
5. `done` — поток закрыт. При обрыве клиента `done` не шлётся, генератор закрывается.

Formatter в проде не стримит свой JSON. Это компилятор блоков: пользователь видит prose через `answer_delta`, а типизированный документ целиком в `result`. Тот же приём у Claude Artifacts и ChatGPT Canvas: текст идёт потоком, структурированный артефакт появляется целиком.

## Fast path

`FormatterFastPathPolicy` пропускает LLM только для prose без структуры
(`plain_paragraph_count` не `None`) и не длиннее `FORMATTER_PASSTHROUGH_MAX_CHARS`,
плюс уверенный worker, совпадение локали и отсутствие review / revision / restructure / choice.
Заголовки, списки и fenced-блоки остаются на LLM независимо от длины.

## Новым агентам

- Структурированный выход не стримить чанками. Отдавать его в `result`.
- Plain text для раннего показа — только через `emit_answer_deltas`.

# Streaming contract: один источник истины на turn (Phase 1.1)

Дополняет `.cursor/plans/evolution-to-big-tech.md` §5–6 (Phase 1 = Hybrid Streaming
Markdown, уже в коде: `text_delta` primary + dual `answer_delta`). Этот файл не
переписывает Phase 1 — он закрывает **оставшийся разрыв**: `schema_first`
не стримит вообще, поэтому structured output приходит одним кадром и заменяет
уже показанный preview. Дублей с 000/040/065/070 не создаём (050).

## 1. Что уже сделано (этот PR, F1)

Гейт «одна перерисовка на turn» + санитизация кадров + метрика + UTF-8:

| Инвариант | Где живёт (единственная точка) |
|---|---|
| ≤1 `replace` за turn, только если что-то нарисовано | `TurnSseBridge.answer_replace_allowed` |
| Что уже видит пользователь | `TurnSseBridge.painted_answer_tail` (bounded 4096) |
| Повторный `answer_delta` тем же текстом — no-op | `TurnSseBridge.answer_already_painted` |
| Внутренние термины не попадают в delta-кадр даже при разрезе по чанкам | `InternalVocabularyPolicy.safe_cut` + `FormatterMarkdownEmitter._paint` |
| Метрика перерисовки | `palatium_sse_layout_shift_total{contract}` |
| UTF-8 на console-стриме | `core/logging/setup.py` (`reconfigure(encoding="utf-8")`) |

Текущий контракт (после F1): при `legacy_markdown` возможен **ровно один**
`replace` — легитимная передача worker-draft → streamed Formatter. Всё остальное
отклоняется. `layout_shift_count` для `legacy_markdown` = 1, для целевого
`structured_incremental` должен быть **0**.

## 2. F2 — реализовано (schema_first стримит блоками)

`schema_first` (`formatter/agent.py:_run_schema_first`) раньше вызывал
`harness.call_llm(..., response_format="json_schema")` — блокирующий вызов, поэтому
в turn'е стримился только worker draft, а затем заменялся финальным
`ContentDocument`. Теперь тот же вызов идёт через `call_llm_stream` (провайдер-
поддержка `stream` + `json_schema` уже была в `harness.py` / `litellm_adapter.py`),
а `PartialDocumentScanner` отдаёт prose каждого закрывшегося элемента `blocks[]`.

### 2.1 Контракт `StreamingContract` (закрытый Literal, 010)

```python
# domain/policies/types.py (SoT — рядом с остальными осями, 055)
StreamingContract = Literal["structured_incremental", "buffered", "legacy_markdown"]
```

| Режим | Кто | Кадры | `layout_shift_count` |
|---|---|---|---|
| `structured_incremental` (цель) | `schema_first` | `answer_delta` (append-only) по мере закрытия объекта в `blocks[]` | **0** |
| `buffered` | неструктурированный/aк-only | один финальный кадр, без preview | 0 |
| `legacy_markdown` (deprecated) | `legacy` fallback | `text_delta` + dual `answer_delta` | 1 (терпимо, kill-switch) |

**Отдельного env-флага нет** (решение при реализации): контракт выводится из той же
двухключевой схемы, что и `FORMATTER_MODE` (`IntentService._stream_contract` →
`resolve_formatter_mode`). Второй флаг допускал бы невозможную комбинацию
`structured_incremental + legacy`, а лечить её пришлось бы downgrade-веткой; здесь
такая комбинация невыразима (055: одно решение, не два источника истины).

### 2.2 Partial JSON → блоки

- `application/agents/formatter/partial_document.py` — инкрементальный сканер
  `blocks[]` на stdlib (счётчик строк/экранирования, `json.loads` каждого
  **закрытого** элемента).
- Парсер НЕ валидирует весь документ до конца: каждый закрытый блок отдаётся
  в SSE, невалидный блок отбрасывается и логируется.
- Никакого `jiter`/`partial-json-parser` без отдельного решения.
- Кадр — `answer_delta` (append-only, `replace` не выставляется) **и**
  `block_delta {index, block}` из того же парса: типизированный блок рисуется
  тем же `BlockRenderer`, что и финальный документ (волна 2 `response-shapes`).
  `answer_delta` остаётся fallback'ом для клиентов без `block_delta`.
- Финальный `result` с `ContentDocument` обязан быть супернабором показанной prose;
  расхождение — ошибка контракта (тест `test_schema_first_paints_blocks_incrementally_without_replacing`).

### 2.3 Worker draft при `structured_incremental`

Preview-worker (`nodes.py:_emit_worker_answer_deltas`, formatter-node draft) в этом
режиме не эмитится: TTFT даёт первый закрытый блок, а не черновик. Гейт —
`TurnSseBridge.structured_preview_active()`, один на оба места.

Ограничение: TTFT первого блока зависит от того, как провайдер отдаёт JSON-дельты.
Пока он медленный, клиент показывает typing indicator (фазовая плашка), а не сырой
текст (DoD п.4: «фаза, а не мигание текстом»).

**Удаление preview-костыля (`nodes.py:423`, `nodes.py:678`)** — только после того,
как `block_delta` даст первый TTFT на маршрутах **без researcher** (formatter-only:
`format_only` / `ack_only`), т.е. там, где draft сегодня и включается. Пока этого
нет, снос preview вернёт «пустой экран до конца ответа» на коротких ходах. Порядок:
сначала `block_delta` на formatter-only в проде (метрика TTFT по маршруту), потом
удаление ветки — отдельным PR с `EXCEPTION`-комментарием не нужен, это не костыль,
а обязательная последовательность.

## 3. Метрики и алерты (040, единый реестр)

- `palatium_sse_layout_shift_total{contract}` — уже добавлена. **Алерт**:
  `increase(...[5m]) > 0` для `contract="structured_incremental"`.
- `palatium_sse_ttft_seconds` — есть; отдельно бюджет по contract-метке.
- Спаны: `stream.first_delta`, `stream.last_delta`,
  `formatter.schema_first.partial_parse` (кол-во отброшенных блоков).
- Новые имена метрик вводить только правкой `core/observability/metrics.py`.

## 4. Тесты (DoD)

1. Contract: в SSE нет ни одного кадра, сбрасывающего уже показанное
   (`test_sse_single_replace_invariant.py` — F1, зелёный).
2. Sanitization: ни в одном delta-кадре нет `attachment_context`, `prior_context`,
   `memory_hints`, `context_packet_json` даже при разрезе термина по границе чанка
   (`test_sse_single_replace_invariant.py` — F1, зелёный).
3. Encoding: кириллица байт-в-байт на пути answer → frames
   (`test_stream_encoding_utf8.py` — F1, зелёный).
4. F2: partial-JSON сканер — unit на «блок закрыт / блок битый / EOF без закрытия»
   (`test_partial_document.py` — зелёный, включая параметризацию по границам чанков).
5. F2: preview аддитивен, финальный документ ⊇ показанных блоков,
   `layout_shift_count == 0` (`test_formatter_schema_first.py` — зелёный).
6. Regression: сценарий «пауза → сырой текст → пауза → замена» не воспроизводится
   на `structured_incremental` (`test_sse_single_replace_invariant.py` — worker draft
   гасится, `answer_delta` не несёт `replace`).

## 5. Роллаут / откат

1. Роллаут — существующий `FORMATTER_ROLLOUT_PCT`: 1 → 5 → 25 → 100, sticky по
   `hash8(user_id)`; контракт стриминга едет вместе с ним (отдельного флага нет).
   Гейт — `layout_shift_count == 0` и `ttft_ms` p95 не хуже baseline.
2. Откат одной переменной: `FORMATTER_ROLLOUT_PCT=0` (MODE не трогаем; turn
   возвращается на `legacy_markdown`), полный kill — `FORMATTER_MODE=legacy`.
3. `legacy_markdown` удаляется отдельным PR после 1 релизного цикла на 100%
   (deprecation, не «заодно»).

## 6. Внешние ориентиры (2026)

- OpenAI Structured Outputs + стриминг: один вызов — один контракт, партиальный
  разбор вместо ожидания полного JSON.
- Anthropic streaming tool use: аргументы инструмента приходят частями,
  UI обновляется инкрементально; невалидная схема — fail fast, без перерисовки
  поверх показанного.
- Gemini function calling: incremental deltas для structured output.
- Vercel AI SDK `streamObject` / `useObject`: партиальный объект рендерится сразу,
  финальный объект его не заменяет.

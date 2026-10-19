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

## 2. Остаточный разрыв (F2 — это план, не реализация)

`schema_first` (`formatter/agent.py:_run_schema_first`) вызывает
`harness.call_llm(..., response_format="json_schema")` — блокирующий вызов.
`call_llm_stream` **уже умеет** `response_format="json_schema"` и пробрасывает
контент-дельты (`application/agents/harness.py:379`, `infrastructure/llm/litellm_adapter.py`),
т.е. не хватает не провайдер-поддержки, а парсера частичного JSON и контракта
кадров. Пока его нет, при `FORMATTER_MODE=schema_first` streaming в turn'е
отсутствует как класс: единственное, что стримится — worker draft, который затем
заменяется финальным `ContentDocument`.

### 2.1 Контракт `StreamingContract` (закрытый Literal, 010)

```python
# domain/ports/streaming.py (SoT)
StreamingContract = Literal["structured_incremental", "buffered", "legacy_markdown"]
```

| Режим | Кто | Кадры | `layout_shift_count` |
|---|---|---|---|
| `structured_incremental` (цель) | `schema_first` | `block_delta` по мере закрытия объекта в `blocks[]` | **0** |
| `buffered` | неструктурированный/aк-only | один финальный кадр, без preview | 0 |
| `legacy_markdown` (deprecated) | `legacy` fallback | `text_delta` + dual `answer_delta` | 1 (терпимо, kill-switch) |

Флаг — отдельный от `FORMATTER_MODE` (065/DoD): `STREAMING_CONTRACT`, роллаут
`STREAMING_CONTRACT_ROLLOUT_PCT` по той же sticky-схеме, что `FORMATTER_ROLLOUT_PCT`
(`core/observability/formatter_rollout.py` — переиспользовать, не копировать).

**Совместимость с `FORMATTER_MODE` (жёсткое правило контракта):**

- `structured_incremental` доступен **только** при `FORMATTER_MODE=schema_first`.
  `block_delta` рождается из структурного парсера; на `legacy` его источника нет.
- Комбинация `structured_incremental + legacy` **запрещена** в
  `resolve_streaming_contract`: она обязана падать в `legacy_markdown` (fail-closed)
  и писать `hitl`-подобный warning `streaming.contract_downgraded`, а не отдавать
  сырой текст в SSE. Иначе возвращается тот самый layout shift, который F2 закрывает.
- `buffered` совместим с любым режимом (финальный кадр), `legacy_markdown` — только
  kill-switch для `legacy`/`schema_first` (deprecated, удаляется отдельным PR).

### 2.2 Partial JSON → блоки

- Новый модуль `application/agents/formatter/partial_document.py`:
  инкрементальный сканер `blocks[]` на stdlib (счётчик строк/экранирования,
  `json.loads` каждого **закрытого** элемента) → `ContentBlock`.
- Парсер НЕ валидирует весь документ до конца: каждый закрытый блок отдаётся
  в SSE, невалидный блок отбрасывается и логируется (`markdown_parser` уже даёт
  такую семантику для MD).
- Никакого `jiter`/`partial-json-parser` без отдельного решения: сначала stdlib,
  зависимость — только если DoD не покрыт (та же политика, что в Phase 1 для
  `markdown-it-py`).
- Кадр: `block_delta {index, block}` — аддитивный, FE **добавляет** блок, не
  перерисовывает предыдущие. Финальный `result` с `ContentDocument` обязан быть
  супернабором показанных блоков; расхождение — ошибка контракта (тест).

### 2.3 Worker draft при `structured_incremental`

Preview-worker (TTFT-костыль `nodes.py:423`, `nodes.py:678`,
`llm_stream.first_token_fallback_watch`) в этом режиме **не эмитится**: TTFT даёт
первый `block_delta`, а не черновик. Это и есть «один источник истины»: убираем
сам предпосыл для `replace`.

Ограничение: TTFT первого `block_delta` зависит от того, как провайдер отдаёт
JSON-дельты. Бюджет `<500ms` — на **первый видимый блок**, при превышении
показываем фазовую плашку (`stream.phase`=working), а не сырой текст
(DoD п.4: «фаза, а не мигание текстом»).

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
4. F2: partial-JSON сканер — unit на «блок закрыт / блок битый / EOF без закрытия»;
   E2E — `block_delta` аддитивны, финальный документ ⊇ показанных блоков,
   `layout_shift_count == 0`.
5. Regression: сценарий «пауза → сырой текст → пауза → замена» воспроизводится на
   `FORMATTER_MODE=schema_first` + `STREAMING_CONTRACT=legacy_markdown` и не
   воспроизводится на `structured_incremental`.

## 5. Роллаут / откат

1. `STREAMING_CONTRACT_ROLLOUT_PCT`: 1 → 5 → 25 → 100, sticky по `hash8(user_id)`;
   гейт — `layout_shift_count == 0` и `ttft_ms` p95 не хуже baseline.
2. Откат одной переменной: `STREAMING_CONTRACT=legacy_markdown` (MODE не трогаем),
   полный kill — `FORMATTER_MODE=legacy` (существующая рампa).
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

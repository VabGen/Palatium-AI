# Internal vocabulary: не пускать служебные имена в ответ пользователю

**Дата:** 2026-10-16 · **Правила:** 020 (guard — код, не промпт), 040, 050, 055 (контракт, не список фраз), 065.

## Симптом

Пользователь получил ответ и HITL-карточку, где вместо объяснения стояли наши имена
полей: «В поле `attachment_context` (загруженные файлы) файл отсутствует», «В
`prior_context` указано…», «В `memory_hints` упоминается…». Ответ ушёл в транскрипт,
транскрипт вернулся в следующий ход как `prior_context` — и жаргон закрепился.

## Причина (контракт, а не фраза)

Мы отдаём модели собственную лексику **дважды**:

1. как **ключи JSON-payload** — `agent_bridge.py` (`context_packet_json`,
   `memory_hints_json`), `llm_research.py`, `critic/agent.py`, `option_synthesizer.py`;
2. внутри **системных промптов** — «If `attachment_context` is non-empty …»
   (`critic/prompts.py`, `context_enricher/continuation/prompts.py`).

Модель зеркалит то, что видит. Значит чинить надо на двух уровнях (055: чини контракт).

## Решение — две линии

| Линия | Где | Что делает |
|---|---|---|
| **1. LLM-facing лексика — пользовательская** | `researcher/llm_research.py` (`attached_files`, `previous_answer`, `user_facts`), `option_synthesizer.py`, промпты | Модель не видит наших имён в полезной нагрузке |
| **2. Детерминированный гейт на выходе** | `domain/policies/internal_vocabulary.py` (`InternalVocabularyPolicy`) | LLM-независимая замена: даже если промпт протечёт или модель вспомнит жаргон, пользователь его не увидит |

Вторая линия обязательна: **инструкция в промпте — не guardrail** (020). Та же роль,
что у `domain/attachments/citations.sanitize_source_refs` для чипов источников.

### Точки применения (все user-facing выходы)

| Выход | Точка |
|---|---|
| Финальный `ContentDocument` (LLM, fast path, deterministic fallback) | `formatter/parsing.py` → `align_formatter_meta` |
| Стриминг ответа (`answer_delta`) | `formatter/answer_delta.py` |
| Стриминг по кадрам | `formatter/stream_delta.py` (+ `safe_cut` — токен-поток не должен разрезать термин пополам) |
| HITL-карточка (framing + label вариантов) | `services/option_synthesizer.py` |

### Что именно вычищается

- Имена полей (`attachment_context`, `prior_context`, `memory_hints`, `context_packet_json`,
  `worker_summary`, `critic_summary`, `underspecification_kind`, …) → нейтральные слова
  («вложения», «предыдущий ответ», «память о вас»). Словарь — **presentation dictionary**
  (`INTERNAL_TERM_REPLACEMENTS`), а не список фраз пользователя: неизвестный жаргон не
  угадывается (055).
- Трафик-идентификаторы: `attachment:<uuid>[:name]` → имя файла (id не проходит),
  `mcp:server.tool` → «инструмент», «голый» UUID → «файл».
- Блоки `code` / `formula` **не трогаются**: это машинный текст, перезапись молча
  испортила бы код пользователя (055).

## Как добавить термин

1. Дописать пару в `INTERNAL_TERM_REPLACEMENTS` (`domain/policies/internal_vocabulary.py`).
   Порядок важен для префиксов (`context_packet_json` длиннее `context_packet`).
2. Параметризованный тест `test_every_known_term_is_rewritten` подхватит новый ключ сам.
3. Если термин приходит из payload/промпта — сначала переименовать ключ на
   пользовательский (линия 1), словарь — только страховка.

## Проверки

`tests/unit/test_internal_vocabulary_policy.py` — contract-тесты: rewrites, идемпотентность,
«не матчим термин внутри другого идентификатора» (`my_memory_hints_x`), code-блоки,
`align_formatter_meta` как граница, `option_synthesizer`, стриминговые дельты,
а также `*_refusal_message_is_user_facing_and_free_of_internal_vocabulary` в
`tests/unit/test_file_reference_policy.py` и `test_refusal_text_never_names_internal_context_fields`
в `tests/unit/test_researcher_file_reread.py`.

## Остатки

Закрыто 2026-10-17: `critic/agent.py` и `critic/prompts.py` больше не называют ключ
`attachment_context` — payload и промпт судьи используют нейтральное `attached_files`
(как Researcher). Регресс-гейт: `test_critic_prompt_uses_neutral_payload_names`
(`tests/unit/test_researcher_full_deliverable.py`).

Ещё открытый остаток — `context_enricher/continuation/prompts.py`: промпт говорит
`has_attachment_context=true`. Пользовательского текста агент не пишет (только JSON-поля),
и `has_attachment_context` — **структурный флаг**, а не поле утечки: словарь
`InternalVocabularyPolicy` матчит термин по границам идентификатора и строку
`has_attachment_context` не трогает. Переименование флага потребует правки
`get_required_context_keys`, bridge и парсинга — отдельная задача, не смешивать с тестами.

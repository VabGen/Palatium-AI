# 0010. Audit W1–W6 closure record (agents package)

- **Статус:** accepted
- **Дата:** 2026-11-10
- **Правило-владелец:** 030 / 040 / 075 / ADR-0009

## Контекст

Аудит `application/agents` (2026-11) прошёл волны W1–W6: verify, contracts,
observability, behavioral evals, inventory. Нужен **снимок закрытия**, чтобы
следующий аудит стартовал от известной baseline и не переоткрывал уже принятые
non-goals (Formatter locale verify, PII fail-soft, off-graph MK/TI).

Это **не** новая оркестрационная политика — запись состояния и триггеров
пересмотра. Норма оркестрации остаётся в [ADR-0009](0009-langgraph-supervisor-workers.md).

## Решение

### 1. Scope (что входило)

| Wave | Содержание |
|---|---|
| W1–W3 / P0–P2 | `verify()`, coder/analyst evals, worker_kind, compact, CriticPolicy, tool metrics, prompt archive, ADR-0009 |
| W4 | verify-матрица для всех агентов, handoffs/run_id, worker_kind в metrics |
| W5 | behavioral evals (steps/tools/handoffs/constitution/enum hygiene) |
| W6 | agent inventory vs LangGraph; off-graph keep |

### 2. Final state (артефакты)

| Артефакт | Где |
|---|---|
| Verify matrix + isolation | ADR-0009; `BaseAgent.verify` docstring |
| Handoff / worker metrics + closed enums | `core/types/agent_observability.py`, `metrics.py` |
| Behavioral budgets | `evals/baselines/behavioral.json`, `evals/behavioral.py` |
| Agent inventory | `evals/agent_inventory.py` (+ таблица в ADR-0009) |
| CI gate | `tests/eval/test_behavioral_evals.py`, `test_agent_inventory.py`, agent cassette baseline |

### 3. Explicit non-goals / reserved

- **Formatter locale `verify()`** — rule-based, достаточен; LLM-judge на Formatter не вводим.
- **CriticPolicy passthrough** — остаётся; Constitution всегда раньше LLM.
- **PII на passthrough → `partial` + `requires_review`** — **осознанный fail-soft**
  (не hard `blocked`): ответ пользователю может уйти, но флаг обязан дойти до
  HITL quality-review mint (`HitlInteractionPolicy.mint_quality_review`), session
  `status=needs_review`, audit `requires_review`, UI `_requiresReview`. Hard-block
  без карточки отвергнут: ломает high-confidence format path и дублирует harness
  secret-redaction. Зафиксировано в ADR-0009 § «Constitution disposition».
- **MemoryKeeper / TextIngestor** — keep off-graph; не мёртвый код. Триггер
  пересмотра — см. §4.

### 4. Review triggers

**Next audit trigger:** следующий *полный* аудит агентов — при (a) смене основной
модели (frontier/standard), (b) добавлении нового агента в граф, (c) истечении
6 месяцев с даты ADR-0010 (2026-11-10 → не позже **2027-05-10**), что наступит раньше.

Дополнительно пересматривать этот closure / ADR-0009 inventory, когда:

1. меняется **Constitution** или CriticPolicy fail disposition;
2. появляется **off-graph orchestration** (единый runner для extract/ingest);
3. PR с `[baseline-refresh]` по `behavioral.json`.

### 5. Baseline management (`behavioral.json`)

- `actual_steps` / `actual_handoffs` — **измеренная** топология графа (не «минимум
  на глаз» и не число LLM-вызовов).
- `max_*` — потолок CI; по умолчанию **равен** `actual_*`.
- Любое увеличение `actual_*` или `max_*` → PR обязан содержать маркер
  **`[baseline-refresh]`** и ссылку на причину (новый hop, осознанный fan-out).
- Тихий drift вверх запрещён (процесс + тест `refresh_policy` schema).

### 6. Ссылки

- [ADR-0009](0009-langgraph-supervisor-workers.md) — orchestration + verify + inventory
- `src/palatium_ai/application/agents/evals/behavioral.py`
- `src/palatium_ai/application/agents/evals/baselines/behavioral.json`
- `src/palatium_ai/application/agents/evals/agent_inventory.py`

### 7. Constitution / verify-prompt hash pins (W7.3)

Неявные правки Constitution или verify-промптов меняют verify-поведение без
видимого сигнала в PR. Пины ниже — CI-контракт (`test_w7_constitution_hash_matches_adr`).
SoT расчёта: `application/agents/evals/constitution_hash.py`.

**Вход в `constitution_sha256`** (sha256 одного файла, полный 64 hex):

- `src/palatium_ai/domain/policies/constitution.py`

**Вход в `verify_prompts_sha256`** (sha256 конкатенации байтов файлов в
стабильном path-order + `\0`-разделитель; полный 64 hex):

- `src/palatium_ai/application/agents/critic/prompts.py`

```
constitution_sha256: c20f23bbdc2cadb413639423003f46e22b28734fddf09ec0fb526a1c281399e7
verify_prompts_sha256: 704e9f54c956be2589efab9e52eb36bb135ac9499669491b3358f6ce8c924348
```

Любое изменение файлов из списков выше → маркер **`[constitution-update]`** в PR
+ обновление этих hash + прогон behavioral evals. См. также ADR-0011 и
`.github/pull_request_template.md`.

## Dialog retention vs HITL «Запомни» (W10.1 P1.2 — choice C)

Live W10 case `2c`: после 10 filler-ходов факт `BGT-42` из T1 не воспроизводится.
Причины (не баг MK on-graph):

1. `dialog_window_size=12` — к T12 user-turn T1 уже вне окна;
2. «Запомни» уходит в HITL `POST /api/memory/save` path / card, а не pin в window;
3. Neo4j promote по-прежнему out-of-band (ADR-0009/0010 off-graph MK).
   W11 (ADR 0013) добавляет **verified fast-path** через durable `MemoryOpQueue`
   после HITL save — chat по-прежнему **не** делает sync Neo4j MERGE на request span.

**Accepted limitation (choice C):** 2c fail в live chat — by design при текущем
окне + HITL persistence. Пересмотр → choice A (retention + HITL параллельно) или
увеличение window / pin user-stated facts — отдельный ADR/продуктовое решение.
Не маскировать 2c как «зелёный» без одного из этих изменений.

## UX: file clarify preempts review (W10.1 P2 — choice A)

Одновременные карточки «выбор файла» + quality-review сбивают пользователя.
**Решение A:** если minted `file_card`, quality-review **не** показывается до
ответа на clarify (`intent_hitl_flow`). Тест-контракт:
`tests/unit/test_w101_clarify_preempts_review.py`.

## Рассмотренные альтернативы

- **Hard-block вместо fail-soft на PII** — отвергнуто: harness уже redact’ит secrets;
  silent drop ответа без HITL хуже, чем `needs_review` + quality card.
- **Оставить behavioral max_* с запасом «на промпт»** — отвергнуто: step count
  топологический; запас маскирует over-orchestration.
- **Удалить MK/TI как «не в графе»** — отвергнуто: живые pipeline-агенты; reserve
  с триггером пересмотра.

## Последствия

- Следующий аудит сравнивает с этим снимком, а не с «чистого листа».
- `[baseline-refresh]` становится явным сигналом в PR-ревью.
- Fail-soft PII нельзя «улучшить» до block без нового ADR.

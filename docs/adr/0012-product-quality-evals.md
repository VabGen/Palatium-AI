# 0012. Product-quality evals (W9)

- **Статус:** accepted
- **Дата:** 2026-11-10
- **Правило-владелец:** 075 / ADR-0009 / ADR-0010 / ADR-0011

## Контекст

W1–W8 закрыли инфраструктуру, контракты и regression-guard'ы (cassette, behavioral,
cost/context ratio). Остаётся дыра: нет эвалов на **качество ответа и диалог** —
«правильно ли», «использован ли контекст», «держится ли диалог», «структурен ли
вывод по смыслу».

## Решение

### Scope (W9.1–W9.4)

| Suite | Что измеряет | Baseline |
|---|---|---|
| W9.1 Semantic | верность фактов / запрет галлюцинаций | `baselines/semantic.json` |
| W9.2 Context utilization | факт X из контекста используется; без X не выдумывается | `baselines/context.json` |
| W9.3 Multi-turn | ссылка на ранний ход / compact / correction | `baselines/multi_turn.json` |
| W9.4 Formatter quality | структура по типу запроса + preserve fields | `baselines/formatter.json` |

Реализация: `application/agents/evals/product_quality/` + `tests/eval/test_w9_*.py`.

### Explicit non-goals

- Не заменяет cassette-regression W1–W8.
- Не гарантирует качество в проде — только ловит регрессии качества в CI/nightly.
- Не оценивает «стиль» и «тон» (отдельная тема при необходимости).
- Не меняет Constitution, промпты агентов, оркестрацию.

### Judge policy

1. **Rule-based first** (`must_contain` / `must_not_contain` / structure / preserve).
2. LLM-judge только если `needs_judge` и **после** успешного rule gate (verifier's law).
3. Judge-промпт версионируется (`JUDGE_PROMPT_VERSION` в `w9_judge_prompts.py`);
   hash пишется ниже; судья не оценивает свои же выходы; провайдер судьи ≠ генератор
   (040 / `assert_provider_independence`).

w9_judge_prompts_sha256: 1b7dc889e975ba3318a093d1160a5077108037216241ddbcdd77ac8df58e6e46

### Baseline management

- Файлы: `semantic.json` / `context.json` / `multi_turn.json` / `formatter.json`.
- Pin: `actual_pass_rate == min_pass_rate` (как behavioral v3 `actual_*==max_*`).
- Изменение потолков — только с маркером **`[baseline-refresh]`** в PR.
- Live suites — nightly (`PALATIUM_LIVE_EVAL=1`); PR держит anti-fiction + schema.

### Review triggers

- Смена основной модели → пересмотр всех W9 baseline.
- Изменение промптов агентов → прогнать W9 live.
- Новый агент → минимум 1 кейс на агента (связка с W8.6 inventory).
- Ревизия judge-рубрик: **не позже 2027-05-10**.

## Formatter disposition (W10.1 P0.1c)

Live W10 показал `status=failure` + `error=formatter_output_invalid` при валидных
`StepsBlock` (howto): HITL InteractionPolicy ошибочно считал процессный timeline
exclusive menu и требовал choice actions. **Политика после W10.1:**

- **Instructional `StepsBlock`** — deliverable content, **не** exclusive picker;
  `menu_shaped=false`, ответ уходит пользователю со `success`/`partial` по обычному
  Formatter path (не `formatter_output_invalid`).
- **Exclusive pickers** — только `ListBlock` / `CalloutBlock` / explicit `actions`.
- **Hard fail-closed** остаётся для настоящего schema/repair failure
  (`invalid_output` → `status=failure`, `confidence=0.0`, **пустые** blocks).
- **Fail-soft** допустим только через `failure_or_fallback` → `status=partial` с
  deterministic document (не «failure + живые blocks»).

Тесты: `tests/unit/test_w101_howto_steps_not_menu.py`,
`tests/unit/test_w101_formatter_disposition.py`,
`tests/unit/test_w101_code_block_requires_text.py`.

## Связи

- ADR-0009 (топология), ADR-0010 (baseline-refresh / closure), ADR-0011 (ratio ≠ utilization).
- `docs/agent-evals.md` § W9.
- Тесты: `test_w9_*.py`.
- Live audit: `docs/audit/w10-live-chat/REPORT.md`, W10.1.

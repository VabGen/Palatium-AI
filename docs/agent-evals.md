# Agent evals (075)

Детерминированные evals на PR; llm_judge — nightly (вне PR-пути).

## Пирамида

| Слой | Где | Запуск |
|------|-----|--------|
| PR deterministic | `application/agents/<name>/evals/tasks.json` + `grader.py` | `scripts/run_agent_evals.py` |
| Cassette harness | `tests/fixtures/llm/<agent>/` | через `cassette` в tasks.json |
| Nightly llm_judge | `application/agents/evals/nightly_tasks.json` | `scripts/run_agent_evals_nightly.py` |
| Live judge smoke | staging ops | `scripts/run_agent_evals_judge_smoke.py` |

## PR CI (deterministic)

```powershell
uv run python scripts/run_agent_evals.py
uv run pytest tests/eval/test_agent_eval_assets.py -q
```

- Baseline: `application/agents/evals/baseline.json` (score per agent + per task).
- Допуск: `EVAL_BASELINE_TOLERANCE` (0.05) в `domain/agents/evals.py`.
- Отчёт: `artifacts/agent_evals.json` (upload в GitHub Actions).

Добавление задачи:

1. Запись в `tasks.json` (`id`, `expect`, `cassette` или `fixture_output`).
2. Фикстура LLM в `tests/fixtures/llm/` при cassette-пути.
3. Порог в `baseline.json` — осознанно в том же PR, что улучшение.

## Nightly (llm_judge)

```powershell
uv run python scripts/run_agent_evals_nightly.py
```

- Задачи: `application/agents/evals/nightly_tasks.json`.
- Baseline: `application/agents/evals/nightly_baseline.json`.
- Workflow: `.github/workflows/agent-evals-nightly.yml` (cron 02:00 UTC + `workflow_dispatch`).

`workflow_dispatch` modes:

| Mode | Описание |
|------|----------|
| `cassette` | judge_cassette (default, cron) |
| `live_smoke` | `run_agent_evals_judge_smoke.py` + live provider |
| `live_full` | полный nightly suite с live judge |

Секреты GitHub: `PALATIUM_EVAL_JUDGE_PROVIDER`, `PALATIUM_EVAL_JUDGE_MODEL`, `PALATIUM_EVAL_AGENT_PROVIDER`, ключи провайдеров.

### pytest llm_live

```powershell
$env:PALATIUM_EVAL_LIVE_JUDGE = "1"
$env:PALATIUM_EVAL_JUDGE_PROVIDER = "anthropic"
$env:PALATIUM_EVAL_AGENT_PROVIDER = "openai"
uv run pytest tests/eval/test_agent_evals_llm_live.py -m llm_live -q

# полный nightly с live judge (дорого):
$env:PALATIUM_EVAL_LIVE_NIGHTLY = "1"
uv run pytest tests/eval/test_agent_evals_llm_live.py::test_nightly_suite_with_live_judge -q
```

Каждая nightly-задача:

1. Гоняет агента через cassette + Harness (`cassette` + `input`).
2. Оценивает выход судьёй (`rubric` + `judge_cassette` по умолчанию).

### Декомпозированный судья (W4)

`judge_mode: "decomposed"` в задаче включает `DecomposedJudgeGrader` (иначе —
прежний `llm_judge`). Вместо одного `score` судья делает **четыре независимых
вызова** — `correctness`, `completeness`, `groundedness`, `tone`, у каждого своя
рубрика (`judge_prompts.DIMENSION_RUBRICS`). Решение принимает
`domain/policies/judge.py`:

| Ось | Норма 040 | Гейт |
|---|---|---|
| `correctness` | accuracy ≥ 6/10 | `score ≥ 0.6` |
| `groundedness` | safety ≥ 8/10 | `score ≥ 0.8` |
| `completeness`, `tone` | нет нормы | измеряются, не блокируют |

- Ось без оценки (сбой вызова) → `missing` → `requires_review`, не «pass».
- Расхождение осей > 0.3 → `divergence=true` в details: сигнал о промпте/модели.
- PII (`contains_pii: true` в задаче или в выходе): внешний судья запрещён (020);
  нужен `PALATIUM_EVAL_INTERNAL_JUDGE_PROVIDER`, иначе `requires_review` без вызовов.
- Cassette нового формата: `{"response": {"dimensions": {"correctness": {"score": …}, …}}}`.
  Ось, которой нет в cassette, остаётся неизмеренной — fixture не подтверждает то,
  что не записано.
- Метрики: `palatium_judge_score{dimension}`, `palatium_judge_failed_total{dimension}`.

### Переменные окружения (judge)

| Переменная | PR CI | Nightly cassette | Live judge (staging) |
|------------|-------|------------------|----------------------|
| `PALATIUM_EVAL_LIVE_JUDGE` | — | не задавать | `1` |
| `PALATIUM_EVAL_JUDGE_PROVIDER` | — | — | `anthropic` / `openai` / … |
| `PALATIUM_EVAL_JUDGE_MODEL` | — | — | опционально |
| `PALATIUM_EVAL_AGENT_PROVIDER` | — | — | провайдер генератора (для проверки независимости) |
| `PALATIUM_EVAL_INTERNAL_JUDGE_PROVIDER` | — | — | внутренний судья для PII-выходов; не задан → `requires_review` |

Правило **040**: судья — модель **другого** провайдера, чем генератор (`generator_provider` в задаче или `PALATIUM_EVAL_AGENT_PROVIDER`). Совпадение → отказ.

Ключи провайдера судьи — те же, что для LiteLLM (`OPENAI_API_KEY`, `ANTHROPIC_API_KEY`, …). Секреты только в CI/Vault, не в git (см. `docs/secrets.md`).

### Live judge smoke (staging)

Проверка связности судьи без полного nightly suite:

```powershell
$env:PALATIUM_EVAL_LIVE_JUDGE = "1"
$env:PALATIUM_EVAL_JUDGE_PROVIDER = "anthropic"
$env:PALATIUM_EVAL_AGENT_PROVIDER = "openai"
$env:ANTHROPIC_API_KEY = "<from-vault>"
uv run python scripts/run_agent_evals_judge_smoke.py
```

## Prompt-change gate (Phase 6)

Промпт — поведение: изменение `application/agents/**/prompts.py` запускает evals
только затронутых агентов (workflow `.github/workflows/prompt-evals.yml`).

```powershell
uv run python scripts/run_prompt_eval_gate.py --changed src/palatium_ai/application/agents/critic/prompts.py
uv run python scripts/run_prompt_eval_gate.py --base-ref origin/dev --report artifacts/prompt_evals.json
```

- Реестр «промпт → агент» — `application/agents/evals/golden_manifest.json`
  (`version` + glob-шаблоны путей; multi-file агенты вроде `context_enricher`
  перечисляют шаблон на подагента, иначе половина промптов теряется).
- Кейсы **не** дублируются: источник — `<agent>/evals/tasks.json`. Шаблон без
  файлов → `GoldenManifestError` (fail-closed на дрейфе реестра).
- Гейт — тот же `run_agent_evals` + `assert_baseline_gate`; пустой набор
  затронутых агентов явно виден в артефакте (`affected_agents: []`).
  Дополнительно строже baseline-допуска: любой упавший кейс затронутого агента
  (а не только падение score ниже baseline − tolerance) — красный гейт.
- `prompt_digest` (sha256 промптов агента) пишется в артефакт для ревьюера.
  Это **не** merge-gate: гейтит только падение eval-score ниже baseline.
- Exit codes: `0` pass/ничего не затронуто, `1` регрессия evals, `2` ошибка конфигурации.

### deepeval (опциональный метрик-бэкенд)

```powershell
uv pip install "deepeval==4.3.1"           # eval-only, НЕ в uv.lock
uv run python scripts/run_prompt_eval_gate.py --changed src/palatium_ai/application/agents/critic/prompts.py --metrics deepeval
```

- `--metrics deepeval` оценивает только задачи с блоком `deepeval`
  (`metric`: `answer_relevancy` | `faithfulness` | `g_eval`, `threshold`, `criteria`).
- deepeval **не** входит в `pyproject`/`uv.lock`: он пинит `rich<15`, а prod-зависимость
  `fastmcp-slim` тянет `rich` — это понизило бы production-зависимость. Установка
  только в dedicated CI-джобе, точным пином.
- Нет пакета → exit `2` (config error); ошибка метрики внутри прогона →
  типизированный `passed=false` с причиной, без трейсбека (035).
- Судья — модель другого провайдера, чем генератор (040); PII-выходы в deepeval
  не отправляются (020).

## Структура cassette

```json
  "response": "{\"task_kind\": \"knowledge_request\", \"requires_mcp\": true}"
}
```

Путь в задаче — относительно `tests/fixtures/llm/` (например `researcher/knowledge.json`).

## Grader protocol

Единый контракт: `domain/agents/evals.py` (`GradeResult`, `Grader`).

- PR: только `kind="deterministic"`.
- Nightly: `kind="llm_judge"` в `application/agents/evals/llm_judge.py`;
  `kind="decomposed_judge"` в `application/agents/evals/decomposed_judge.py`
  (per-task `judge_mode: "decomposed"`, W4).

## См. также

- `.cursor/rules/075-testing-evals.mdc`
- `docs/max-pro-level-tz.md` §13

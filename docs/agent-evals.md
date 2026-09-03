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
poetry run python scripts/run_agent_evals.py
poetry run pytest tests/eval/test_agent_eval_assets.py -q
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
poetry run python scripts/run_agent_evals_nightly.py
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
poetry run pytest tests/eval/test_agent_evals_llm_live.py -m llm_live -q

# полный nightly с live judge (дорого):
$env:PALATIUM_EVAL_LIVE_NIGHTLY = "1"
poetry run pytest tests/eval/test_agent_evals_llm_live.py::test_nightly_suite_with_live_judge -q
```

Каждая nightly-задача:

1. Гоняет агента через cassette + Harness (`cassette` + `input`).
2. Оценивает выход судьёй (`rubric` + `judge_cassette` по умолчанию).

### Переменные окружения (judge)

| Переменная | PR CI | Nightly cassette | Live judge (staging) |
|------------|-------|------------------|----------------------|
| `PALATIUM_EVAL_LIVE_JUDGE` | — | не задавать | `1` |
| `PALATIUM_EVAL_JUDGE_PROVIDER` | — | — | `anthropic` / `openai` / … |
| `PALATIUM_EVAL_JUDGE_MODEL` | — | — | опционально |
| `PALATIUM_EVAL_AGENT_PROVIDER` | — | — | провайдер генератора (для проверки независимости) |

Правило **040**: судья — модель **другого** провайдера, чем генератор (`generator_provider` в задаче или `PALATIUM_EVAL_AGENT_PROVIDER`). Совпадение → отказ.

Ключи провайдера судьи — те же, что для LiteLLM (`OPENAI_API_KEY`, `ANTHROPIC_API_KEY`, …). Секреты только в CI/Vault, не в git (см. `docs/secrets.md`).

### Live judge smoke (staging)

Проверка связности судьи без полного nightly suite:

```powershell
$env:PALATIUM_EVAL_LIVE_JUDGE = "1"
$env:PALATIUM_EVAL_JUDGE_PROVIDER = "anthropic"
$env:PALATIUM_EVAL_AGENT_PROVIDER = "openai"
$env:ANTHROPIC_API_KEY = "<from-vault>"
poetry run python scripts/run_agent_evals_judge_smoke.py
```

## Структура cassette

```json
{
  "response": "{\"task_kind\": \"knowledge_request\", \"requires_mcp\": true}"
}
```

Путь в задаче — относительно `tests/fixtures/llm/` (например `researcher/knowledge.json`).

## Grader protocol

Единый контракт: `domain/agents/evals.py` (`GradeResult`, `Grader`).

- PR: только `kind="deterministic"`.
- Nightly: `kind="llm_judge"` в `application/agents/evals/llm_judge.py`.

## См. также

- `.cursor/rules/075-testing-evals.mdc`
- `docs/max-pro-level-tz.md` §13

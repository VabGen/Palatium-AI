# Evals Phase 6 — golden corpus · prompt-PR gate · deepeval metrics

Статус: **S1 DONE (2026-10-25) · S2 DONE (2026-10-25) · S3 DONE (2026-10-25)**.
Родитель: `.cursor/plans/evolution-to-big-tech.md` §8, строка **Phase 6**.
Норматив: 075 (тесты/evals, не ослаблять), 040 (судья — другой провайдер),
020 (секреты/PII в судейских вызовах), 025 (supply chain), 050/055 (один владелец
решения, без дублей), 010 (типы), 005 (этот документ — спека до кода).

---

## 0. Разрыв, который закрываем

| # | Разрыв | Где видно |
|---|---|---|
| R1 | Golden-набор существует, но не **привязан к промптам**: изменение `prompts.py` не требует прогона затронутых evals | `ci_quality.py` гоняет все evals всегда — дорого/шумно, а PR-гейта «этот промпт → эти кейсы» нет |
| R2 | Нет реестра «промпт-файл → агент → eval-кейсы»; соответствие держится в голове | `application/agents/evals/` |
| R3 | Нет метрик качества **ответа** (relevancy/faithfulness), только детерминированные expectations и собственный llm-judge | `application/agents/evals/` |
| R4 | Нет CI-события «промпт изменился» — nightly ловит регрессию через сутки | `.github/workflows/` |

## 1. S1 — golden manifest (реестр промптов, не копия кейсов)

`application/agents/evals/golden_manifest.json` — единственный новый источник:
версия набора + для каждого агента **шаблоны путей** его промптов.

```json
{ "version": "2026.10.1",
  "agents": { "context_enricher": { "prompts": ["application/agents/context_enricher/*/prompts.py"] } } }
```

- Кейсы **не** дублируются: источник задач остаётся
  `application/agents/<agent>/evals/tasks.json` (050: второй список кейсов — второй SoT).
- Шаблон, не совпавший ни с одним файлом, — ошибка загрузки (`GoldenManifestError`),
  а не «пустой промпт» (055: fail-closed на дрейфе реестра).
- `prompt_digest(agent)` = sha256 по (relpath, bytes) всех промптов агента. Дайджест
  **репортится**, но не гейтит: гейт — падение eval-score ниже baseline. Дайджест-гейт
  требовал бы reblessing на каждый осмысленный промпт-фикс и превращался бы в
  формальность (050: декоративных гейтов не вводим).

## 2. S2 — prompt-PR gate

`application/agents/evals/prompt_gate.py`:

- `agents_for_changed_paths(paths)` — маппинг «изменённый путь → агент» из манифеста:
  промпт-файл агента **или** `application/agents/<agent>/evals/**`.
- `run_prompt_gate(paths)` → `PromptGateResult(changed_paths, affected_agents, digests,
  reports, failures)`. Кейсы гоняются через `run_agent_evals` (тот же runner, тот же
  baseline), затем `assert_baseline_gate` — переиспользование, ноль второй логики порогов.
- Нет затронутых агентов → `passed=True` и пустые reports (не «зелёный по молчанию»:
  явное поле `affected_agents=()` в артефакте).

`scripts/run_prompt_eval_gate.py` — CLI для CI:

```powershell
uv run python scripts/run_prompt_eval_gate.py --base-ref origin/dev --report artifacts/prompt_evals.json
```

Workflow `.github/workflows/prompt-evals.yml`: `pull_request` по путям
`application/agents/**/prompts.py` и `application/agents/evals/**`, действия запинены
по SHA (025), артефакт — отчёт гейта.

## 3. S3 — deepeval как **опциональный** метрик-бэкенд

- **Не** в `pyproject`-группах и **не** в `uv.lock`: deepeval пинит `rich<15`, а
  `fastmcp-slim` (prod-зависимость) тянет `rich` — добавление в lock **понижает**
  prod-зависимость до 14.3.4 (проверено `uv lock`: `rich 15.0.0 → 14.3.4`). Это побочный
  регресс прода от dev-инструмента (025/055) — недопустимо.
  Установка — только в dedicated CI-джобе поверх синкованного окружения:
  `uv pip install "deepeval==4.3.1"` (точный пин). Lockfile проекта не меняется.
- `application/agents/evals/deepeval_grader.py`:
  - `DeepEvalSpec` (`metric`: `answer_relevancy` | `faithfulness` | `g_eval`,
    `threshold`, `criteria` для `g_eval`);
  - `DeepEvalGrader` принимает `runner` (DI). Дефолтный runner импортирует deepeval
  **лениво** внутри вызова; без пакета CLI завершается кодом 2 (config error), а сам
  грейдер возвращает типизированный `GradeResult(passed=False, details="deepeval
  backend unavailable…")`, не трейсбек (035 fail-closed на границе).
  - `run_deepeval_evals(agent)` гоняет только задачи с блоком `deepeval`, оценка —
    cassette-выход агента (075: метрика не заменяет детерминированный PR-гейт).
- Судья deepeval — модель **другого** провайдера, чем генератор (040): проверка
  остаётся на `PALATIUM_EVAL_JUDGE_PROVIDER`/`PALATIUM_EVAL_AGENT_PROVIDER`.
  PII-выходы (`contains_pii`) в deepeval не отправляются (020).
- В PR-workflow deepeval-шаг выполняется только при наличии ключей провайдера
  (fork PR — нет секретов → шаг пропускается с явным сообщением, а не «pass»).

## 4. Критерии приёмки

1. Манифест покрывает все агенты с `evals/`; шаблон без файлов → `GoldenManifestError`.
2. `agents_for_changed_paths` маппит промпты (включая multi-file `context_enricher/*/prompts.py`),
   `evals/**` и не мапит посторонние пути.
3. Гейт падает на регрессии eval-score и проходит на baseline; отчёт сериализуется.
4. `tests/unit/test_deepeval_grader.py` работает **без** установленного deepeval (DI-fake);
   отсутствие пакета — типизированный fail, не ImportError наружу.
5. Workflow-контракт проверен тестом (триггеры, SHA-пины, команда гейта, secret-gate).
6. `ci_quality.py` остаётся зелёным; default-окружение не тянет deepeval.

## 5. Вне scope

- PyRIT / полноценный adversarial-фреймворк (своя волна; Phase 5 уже дал corpus).
- Замена детерминированных evals на LLM-метрики в PR-пути — запрещено 075.
- Автообновление baseline скриптом: baseline меняет человек в PR с улучшением (075).

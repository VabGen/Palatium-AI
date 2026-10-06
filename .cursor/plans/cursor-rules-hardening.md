# План: усиление и дополнение `.cursor` (Engineering Quality 2026)

Обновлено: 2026-09-30.
Источник: черновик пользователя «полный стек правильного программирования на 2026»
+ аудит репозитория (правила, hooks, CI, `pyproject.toml`, `web/`, `docs/`).

Статус: **PLAN**. Этот документ — вход/навигация, а **не** норматив.
Норматив — `.cursor/rules/*.mdc` (индекс: **099**). После реализации каждой волны
её содержание уходит в правило, а здесь остаётся только статус.

Волны W0–W6 закрыты 2026-09-30 (см. §4); открытые вопросы — §7, backlog гейтов — §5.
Отклонённое фиксируется явно (`commitlint`, branch protection, `ty` как гейт, SBOM
до релиза), чтобы это не переоткрывалось заново.

---

## 0. Принципы этого плана

1. **Не дублировать запреты** (050). Новая тема → новый файл-владелец; существующая
   тема → правка ОДНОГО владельца. Дубль правила по файлам — сам антипаттерн.
2. **Правило без гейта — не правило.** У каждого нового правила должен быть
   enforcement: `hooks.json`, `.pre-commit-config.yaml`, `scripts/ci_quality.py`,
   `scripts/ci_security.py` или соответствующий тест (040, «никогда потом»).
3. **Всё непроверенное — помечено `verify`.** Числа и внешние категории не
   попадают в правила как факт без источника.
4. **Волна = правило + конфиг + гейт + DoD.** Иначе это не волна, а backlog.

---

## 1. Вердикт по черновику

Разбор каждого тезиса: что взять, что переформулировать, что отклонить.

| № | Тезис черновика | Факт-чек | Решение |
|---|---|---|---|
| 1 | **Spec-Driven Development (SDD)** — спецификация = единый источник истины | Согласуется с моделью `plans/` + rules + `wip`-дисциплиной проекта | **Взять** → новое правило `005-spec-driven-development` |
| 2 | Python-стандарт типизации 2026 — **Ty** | Проверено 2026-09-25: `ty` — **0.0.x beta**, Stable-milestone 84%, «не имеет стабильного API, breaking changes между версиями», Astral сама рекомендует «motivated users» | **Отклонить как гейт.** Проект остаётся на `mypy --strict` (уже в hook + CI). `ty` — необязательный быстрый локальный фидбек, не замена. |
| 3 | **OWASP Top 10:2025** (не «2026 edition») | Подтверждено (owasp.org/Top10/2025). A01 Broken Access Control, A02 Security Misconfiguration (+c #5), A03 Software Supply Chain Failures, A04 Cryptographic Failures, A05 Injection, A06 Insecure Design, A07 Authentication Failures, A08 Software or Data Integrity Failures, A09 Security Logging **& Alerting** Failures, A10 Mishandling of Exceptional Conditions | **Взять с уточнением.** Черновик пропустил A04–A09 и неточно назвал A09. |
| 4 | «+41% сложности, +30% warnings от AI-кода» | Не подтверждено первоисточником | **Не кодировать числа.** Мотивация — без цифр либо с пометкой `verify` + ссылка. |
| 5 | «Кеш ускоряет на 85–87%, async +700–860%» | Не подтверждено; зависит от нагрузки | **Убрать числа** из правила. |
| 6 | `Ruff` заменяет Black/isort/Flake8; строгая типизация | Верно; в проекте уже enforced: `ruff check`, `ruff format --check`, `mypy --strict` | **Взять как данность** → правило-владелец `015-code-quality` |
| 7 | Порог цикломатической сложности > 10 — проблема; вложенность > 3 | В `pyproject.toml` уже `[tool.ruff.lint.mccabe] max-complexity = 10` (осознанный ratchet в комментарии) | **Взять**; добавить «вложенность ≤ 3» и мягкий лимит длины функции → `015` |
| 8 | Exception handling: **fail closed**; клиенту общее, детали в лог | Согласуется с 020/030.8; OWASP A10 это подтверждает | **Взять** → новое правило `035-error-handling` |
| 9 | Управление секретами, allowlist-валидация, параметризованные запросы, RBAC на сервере | Уже покрыто 020/070 | **Не дублировать.** Добавить только OWASP-маппинг и supply chain. |
| 10 | Memory leaks, N+1, O(n²), кеш, async | Частично: 050 (одна строка про blocking в `async def`) | **Взять** → новое правило `080-performance` |
| 11 | Пирамида тестов 60–75/20–30/5–10, Vitest 4 / RTL / MSW / Playwright | В `web/` **нет** тестовой инфраструктуры (нет vitest/playwright в `web/package.json`); backend-пирамида в 075 есть | **Взять как цель** → правки `075` + новое `084-frontend-quality` |
| 12 | Docker multi-stage, pin base images by **digest**, Argo CD / GitOps, Terraform | В репо есть Dockerfile/compose; правила-владельца нет. Argo/Terraform отсутствуют | **Взять частично** → `082-delivery`; IaC-инструмент выбирается отдельно, не «навязывать» (050). |
| 13 | Prometheus+Grafana, Loki+Promtail | Prometheus уже в 040 и `deploy/observability/` | **Не дублировать**, сослаться на 040. |
| 14 | docs-as-code, README, OpenAPI 3.2.0, комментарии «почему», TODO/FIXME | Правила-владельца нет | **Взять** → `086-documentation`. Версию OpenAPI **не** хардкодить без сверки. |
| 15 | SOLID/DRY/KISS/YAGNI | Частично в 000/050 (God Agent, дублирование) | **Взять** как явный раздел в `015` |

### 1.1. Дрейф документации, найденный при аудите

| Файл | Что устарело | Факт |
|---|---|---|
| `099-project-map.mdc` | «React 18 + Vite» | `web/package.json`: **react ^19.1.1** |
| `010-typing-strict.mdc` | заголовок «Python 3.12+» | `pyproject.toml`: `requires-python = ">=3.14,<3.15"` (target `py314`) |
| `web/` | ESLint/Prettier настроены, но **не** в npm-скриптах и **не** в CI | `package.json` scripts: только `dev/build/preview` |

---

## 2. Матрица покрытия (черновик → правило → пробел)

| Раздел черновика | Текущий владелец | Пробел → действие |
|---|---|---|
| Архитектура, SOLID, антипаттерны | `000`, `030`, `050` | Нет явного раздела DRY/KISS/YAGNI и «размер функции» → в `015` |
| Spec-Driven Development | — | **Нет** → `005` |
| Code style / Ruff / complexity | `010` (только типы) + `pyproject` | Нет правила-владельца стиля/сложности/вложенности → `015` |
| Обработка ошибок / A10 | `020`, `030.8`, `040` | Нет общего контракта fail-closed / bare-except → `035` |
| Безопасность (OWASP) | `020` | Нет OWASP-маппинга, per-endpoint AC, misconfig → правка `020` |
| Supply chain | CI (`ci_security.py`, `dependabot.yml`) | Нет правила → `025` |
| Производительность | `050` (1 строка) | Нет правила → `080` |
| Testing / QA | `075` | Нет пропорций пирамиды и frontend-тестов → правка `075` + `084` |
| DevOps / CI-CD / Docker | — | **Нет** → `082` |
| Документация | — | **Нет** → `086` |
| Git / PR | — | **Нет** → `088` |
| Frontend | `099` (упоминание) | **Нет** правила качества фронта → `084` |

Итог: **9 новых правил** (005, 015, 025, 035, 080, 082, 084, 086, 088)
и **правки 5 существующих** (010, 020, 050, 075, 099).

---

## 3. Переработанный черновик → декомпозиция по правилам

Ниже — нормализованное (исправленное) содержание черновика, разложенное по будущим
файлам. Ключи правил выбраны так, чтобы лечь в существующую десятичную сетку
(00x — фундамент/процесс, 01x — качество/типы, 02x — безопасность, 03x — контракты,
08x — свободный блок delivery/frontend).

### 3.1. `005-spec-driven-development.mdc` (новое, 00x)

**Scope:** процесс «спецификация → код», а не архитектура.

- Любое изменение > 1 файла или новое правило/агент/tool/MCP-инструмент начинается
  со спецификации: `.cursor/plans/<тема>.md` (или issue) со scope, DoD, enforcement.
- Спецификация — **единственный** источник намерения; код ссылается на неё в PR.
- Один PR = одна спецификация; расширение scope в PR — нарушение.
- При конфликте «черновик/чат» и действующего правила — **правило побеждает**
  (уже зафиксировано в `070`, `092`; обобщается здесь).
- **Enforcement:** шаблон PR (ссылка на spec), checklist ревью.
- **DoD:** шаблон PR добавлен; процесс описан одной страницей; нет дубля с 055.

### 3.2. `015-code-quality.mdc` (новое, 01x) — владелец стиля и сложности

**Scope:** читаемость, размер, дублирование, именование, docstrings.

- **Ruff — единственный** линтер/форматтер; наборы уже включены в `pyproject.toml`
  (`E,F,W,C90,I,UP,B,SIM,S,D,N,TC`); менять набор — только в этом файле + `pyproject`.
- Метрики: **cyclomatic complexity ≤ 10** (ruff `C90`, уже enforced); **глубина
  вложенности ≤ 3**; длина функции — ориентир ≤ 50 строк (soft, повод к декомпозиции,
  не гейт). Длинная функция со сложностью 25 — BLOCK по ревью.
- DRY / KISS / YAGNI: абстракция «на будущее» — YAGNI-нарушение; дубликат логики
  (кроме тестов) — предупреждение; мёртвый и закомментированный код — удалять.
- Именование: доменные имена (сущности), без `data`/`info`/`tmp`/`manager`-обманок;
  сокр. только общепринятые (`id`, `url`, `http`).
- Docstrings: **почему/контракт**, не пересказ «что»; публичные границы — коротко.
- **Ratchet-бэклог (руфф-наборы, волнами):** `DTZ` (naive datetime — прямо
  поддерживает правило 050 `datetime.now(UTC)`), `T20` (запрет `print`),
  `BLE` (blind except), `ASYNC` (blocking в async), `RET`, `PTH`, `A`, `INP`,
  `G`/`LOG`. Включать по одному с `per-file-ignores` для легаси, затем снимать.
- **Enforcement:** `python-quality-gate.sh`, `ci_quality.py`, pre-commit (уже);
  расширение `select` — в этой волне.
- **DoD:** правило + расширенный `select` + CI зелёный + список ratchet-исключений.

### 3.3. `025-supply-chain-security.mdc` (новое, 02x) — OWASP A03/A08

**Scope:** зависимости, lockfile, образы, CI-supply-chain.

- `poetry.lock` обязателен и синхронен: гейт `poetry check --lock` в CI.
- Диапазоны версий — с верхней границей (уже практика) и **обоснованием** в
  комментарии при пине (уже делается для `cryptography`/`openai`).
- SCA: `pip-audit` — блокирующий; единственный путь «принять риск» —
  `security/pip-audit-ignore.txt` с ID advisory (уже есть).
- Базовые образы Docker — пин по **digest**, не по mutable-тегу (см. `082`).
- GitHub Actions — пин по commit SHA с комментарием версии для сторонних action
  (решение 2026-09-30, W2): дрейф ловит `ci_security.py`, бампы — PR dependabot.
- Обновления: `dependabot.yml` покрывает pip/actions/npm/docker (уже есть).
- SBOM/provenance — **backlog** (решение 2026-09-30: уровень зрелости ниже текущих гейтов).
- **Enforcement:** `ci_security.py` (`poetry check --lock` + pin-drift + `pip-audit`)
  + gitleaks (есть); негативные тесты — `tests/unit/test_ci_security_gates.py`.
- **DoD:** правило + lock-гейт в CI + таблица трекинга принятых advisory. ✔ W2

### 3.4. `035-error-handling.mdc` (новое, 03x) — OWASP A10

**Scope:** классификация и обработка исключений на границах.

- **fail-closed** на границах доверия (auth, ACL, сканеры, HITL): сбой проверки →
  отказ, не «пропустить».
- Запрещены: голый `except:` / `except Exception: pass` (глотание), логирование
  исключения без `trace_id`, возврат внутренних деталей клиенту.
- Классификация при обработке:
  - **programming error** (`ValueError` на неверном входе домена) — падать (030.8);
  - **expected operational error** (таймаут/tool/permission) — типизированный
    результат, не проброс наружу (030.8, 070.3);
  - **boundary** (FastAPI, MCP) — маппинг в публичный код/сообщение, детали — в лог.
- Retry/backoff/circuit breaker — только через `core/resilience` (020), не в `except`.
- **Enforcement:** ruff `BLE`/`TRY`/`S`; тест-паттерн «RBAC-отказ не пробрасывает
  `PermissionError`» (уже в 075).
- **DoD:** правило + ruff-наборы + regression-тест на fail-closed.

### 3.5. `080-performance.mdc` (новое, 08x)

**Scope:** производительность и доступ к данным.

- **Никаких блокирующих вызовов в `async def`** (`time.sleep`, sync `requests`,
  sync-драйвер) — `asyncio.sleep` / async-клиенты / `asyncio.to_thread` (уже строка
  в 050 → здесь полноценный владелец).
- **N+1:** batch/eager loading (JOIN/`selectinload`) вместо запроса в цикле.
- Списочные ответы — обязательная **пагинация** с ограничением сверху (константа в
  `core/types`, не магия).
- Кэш — только с **лимитом размера + TTL + метрикой**; неограниченный кэш запрещён
  (утечка памяти). Инвалидация описана там же, где кэш.
- Ресурсы: async context managers; снятие слушателей/таймеров (бэкенд и фронт — 084).
- Алгоритмы: осознанно избегать O(n²) на больших коллекциях; сложность — в docstring
  для неочевидных мест.
- **Enforcement:** ruff `ASYNC`; метрики из 040 (`*_duration_seconds`); perf-тест
  из 075 (маркер `slow`, не PR-путь).
- **DoD:** правило + `ASYNC` включён + perf-тест на регрессию.

### 3.6. `082-delivery-devops.mdc` (новое, 08x)

**Scope:** сборка, доставка, окружения.

- Docker: multi-stage, **non-root** runtime, base image по digest (025), секреты —
  только через env/volume, никогда в слоях/образах.
- CI — обязательные гейты: `ci_quality.py` + `ci_security.py` (есть) + новый web-job
  (084). Merge при красном CI — запрещён.
- Окружения: конфиг — из env/секретов (020); никаких «прод-значений» по умолчанию.
- Миграции БД — отдельный шаг деплоя, forward-only, проверяются в CI; `downgrade`
  в проде — только осознанным решением.
- GitOps/IaC (Argo CD/Terraform/Pulumi) — **решение отдельное**; инструмент не
  добавляется молча (050). До решения — артефакт: `Dockerfile` + compose + workflow.
- **Enforcement:** workflow + `docker compose config --quiet` (Makefile `validate`).
- **DoD:** правило + web-job в CI + `poetry check --lock`.

### 3.7. `084-frontend-quality.mdc` (новое, 08x) — React 19 + Vite + TS

**Scope:** `web/`.

- TS strict (`web/tsconfig.json` уже `strict`, `noUnused*`) — обязателен; `any` на
  границах API запрещён (типы в `web/src/types/`).
- ESLint + Prettier — `web/eslint.config.js`, `.prettierrc`, `.prettierignore`; скрипты
  `lint`/`lint:fix`/`format`/`format:check` + агрегат `verify` (082).
  **Уточнение факта (2026-09-30, W4):** конфиги лежали в репозитории без зависимостей и
  скриптов, а правила `react-hooks` не были включены — то есть гейта не существовало.
  Линтер — ESLint 10 (`eslint-plugin-react`/`jsx-a11y` держат peer `^9`, а 9 снят с
  поддержки), React-правила — `@eslint-react/eslint-plugin`.
- React: эффекты всегда с cleanup (нет утечек таймеров/подписок — 080); данные —
  без N+1-запросов; состояние — не дублировать в нескольких местах.
- Тесты (пирамида, как в 075): unit/component — **Vitest + React Testing Library**;
  интеграция — **Vitest + MSW** (реальные HTTP-моки, не «лживые» моки клиента);
  E2E — **Playwright**, только критические сценарии (HITL-карточки, ingest, память).
- a11y: клавиатура, роли/aria, контраст; lottie-анимации — уважать
  `prefers-reduced-motion` (согласуется с web-craft скиллами).
- Perf: bundle-budget, code-split для тяжёлых блоков, запрет блокирующих синхронных
  операций в рендере.
- **Enforcement:** существующая CI-джоба `frontend` (одна установка на все фронт-гейты,
  второй job дублировал бы `npm ci`): `npm run verify` (`typecheck && lint &&
  format:check && test`) → `cem:check` → `build:widget` → `verify:widget` → `test:e2e`.
- **DoD:** скрипты + CI-job + первый smoke-тест (Vitest) + правило. ✔

### 3.8. `086-documentation.mdc` (новое, 08x)

**Scope:** документация как код.

- docs-as-code: `docs/*.md` + `README.md` обновляются в том же PR, что поведение.
- OpenAPI — генерируется из Pydantic/FastAPI; ручной рассинхрон — BLOCK. Версию
  спецификации не хардкодить без сверки (`verify`).
- Комментарии: **почему**, а не что; не комментировать очевидное; не оставлять
  закомментированный код (015).
- TODO/FIXME: формат `TODO(owner, ticket, date): ...`; без owner/ticket — запрещён;
  CI-скан (`scripts/check_todos.py`) выдаёт «мёртвые» TODO.
- ADR: архитектурно значимые решения — короткий ADR в `docs/adr/` (по мере
  необходимости, не бюрократия).
- **Enforcement:** TODO-сканер в CI; добавление в docs-index (`docs/README.md`).
- **DoD:** правило + сканер + обновлённый `docs/README.md`.

### 3.9. `088-git-workflow.mdc` (новое, 08x)

**Scope:** ветки, коммиты, PR, ревью.

- DIRECT PUSH в `main/master` не делаем; изменения — через PR. **Branch protection —
  не вводим** (решение пользователя, 2026-09-30): правило фиксирует рабочий договор,
  а техническая защита ветки остаётся настройкой репозитория, не скриптом проекта.
- Conventional Commits (`feat/fix/docs/refactor/chore`), сообщение — по существу,
  как договор в правиле. **`commitlint` — не вводим** (то же решение): формат коммита
  проверяется ревью, а не гейтом в pre-commit/CI.
- PR атомарный: один scope; большой рефакторинг + фича — разделять.
- В описании PR: ссылка на spec/правило (005), что затронуто, как проверено (тесты).
- `.cursor/rules/**` и `mcp_servers/edms/JavaEdms/**` — под CODEOWNERS (090);
  правило нельзя менять «попутно» в несвязанном PR.
- **Enforcement:** шаблон PR + CODEOWNERS (ops). Гейтов на ветку/сообщение коммита нет.
- **DoD:** правило + шаблон PR (+ CODEOWNERS — ops).

### 3.10. Правки существующих правил (не новые файлы)

| Файл | Что добавить | Почему не дубль |
|---|---|---|
| `099-project-map.mdc` | индекс +9 правил; **React 18 → 19**; строка про frontend-правило | Единственная навигация по правилам |
| `010-typing-strict.mdc` | «Python 3.12+» → «Python 3.14» (сверить с `requires-python`) | Устранить дрейф, не новое правило |
| `020-security-hitl.mdc` | таблица OWASP:2025; A01 «AC на КАЖДОМ эндпоинте, deny-by-default»; A02 misconfig; ссылки на `025`/`035`/`082` | 020 — владелец безопасности; supply chain/ошибки выносим отдельно, здесь только маппинг |
| `050-anti-patterns.mdc` | строки: неограниченный кэш; отсутствие cleanup; `except: pass`; N+1; mutable base image; мёртвый TODO; функция > 50 строк / вложенность > 3 | 050 — таблица запретов; новые запреты = строки, не файлы |
| `075-testing-evals.mdc` | пропорции пирамиды (60–75/20–30/5–10); ссылка на frontend-тесты `084`; ratchet global coverage (`PALATIUM_COV_MIN_GLOBAL`) | 075 — владелец тестов |

---

## 4. Волновой план

Порядок — от нулевого риска к высокому. Каждая волна мержится отдельно и
не расширяет scope.

### W0 — Снятие дрейфа и индекс · **DONE (2026-09-25)**
- `099`: React 18 → **React 19 + Vite + TypeScript**; Tailwind → **plain CSS**
  (`web/src/styles.css`; Tailwind в проекте не подключён); добавлен указатель на план.
- `010`: «Python 3.12+» → **Python 3.14** (3 места); добавлена явная привязка к
  `mypy --strict` и зафиксировано, что `ty` не используется как гейт.
- `050`: добавлено 7 строк-запретов (кэш, cleanup, `except: pass`, N+1, mutable
  image tag, мёртвый TODO, размер функции/вложенность).
- `.cursor/skills/web-craft/SKILL.md`: снят дрейф React 18 / Tailwind.
- Сверка `docs/` ↔ правила: расхождений по версиям нет (mypy/ruff упомянуты верно).
  Единственный найденный, вне scope W0: `docs/runbook.md` содержит `poetry run mypy .`
  — привести к `mypy --strict src/palatium_ai` в W1.
- **DoD:** `ci_quality.py` зелёный (`.mdc` не в scope ruff/mypy, но diff чист). ✔

### W1 — Качество кода и ошибки · **DONE (2026-09-25)**
- Созданы правила `015-code-quality` и `035-error-handling`; `099` — индекс обновлён.
- `pyproject.toml`: `select += DTZ, T20, BLE, ASYNC` (ratchet, комментарии по каждому).
- `per-file-ignores` ratchet:
  - `tests/**` += `DTZ` (тесты намеренно строят naive datetime);
  - `scripts/**` += `T20`, `BLE` (CLI: stdout + broad-catch → exit-code);
  - `.cursor/hooks/**` += `T20`, `BLE` (протокол хуков + fail-closed);
  - `src/palatium_ai/application/**` и `src/palatium_ai/infrastructure/**` = `BLE`
    (граничные broad-catch; сужение по сайтам отложено — в W3 долг записан явным
    `TODO(...)` в `pyproject.toml` и строкой в §5, см. ниже);
  - `domain/core/presentation` BLE проверяются **уже сейчас**.
- Исправлен реальный блокирующий вызов: `bootstrap.py` `Path.exists()` в async →
  `await asyncio.to_thread(path.exists)` (ASYNC240, 080).
- `050`: строки-запреты уже ссылаются на 015/035 (сделано в W0).
- **DoD:** `ruff check .` — «All checks passed!»; `ruff format --check .` — 676 files
  already formatted. ✔
- **Примечание:** `mypy --strict` в песочнице запустить не удалось (в venv нет
  `type-check`-группы) — проверка выпадет на CI (`scripts/ci_quality.py`).
  Изменение `bootstrap.py` тривиально типобезопасно (`asyncio.to_thread` → `bool`).
- **Перенос в W3:** `docs/runbook.md` — `poetry run mypy .` → `mypy --strict src/palatium_ai`.

### W2 — Безопасность и supply chain · **DONE (2026-09-30)**
- Создано правило `025-supply-chain-security` (lock, диапазоны, SCA-триаж, образы,
  Actions, обновления, SBOM-backlog); `020` — добавлена **карта владельцев OWASP
  Top 10:2025** (навигация по владельцам, не второй список запретов — 050);
  `099` — индекс обновлён.
- Гейты добавлены в `scripts/ci_security.py` (шаг supply-chain, до `pip-audit`):
  - `poetry check --lock` — рассинхрон lock и манифеста роняет CI;
  - pin-drift: любая `uses:` без 40-символьного SHA **и** без комментария версии
    роняет CI (локальный `./…` action исключён — пинить нечего).
- Actions запинены по commit SHA с комментарием версии: `checkout` v4.4.0,
  `setup-python` v5.6.0, `setup-node` v4.4.0, `upload-artifact` v4.6.2,
  `gitleaks-action` v2.3.9 — во всех четырёх workflow. Пины сверены с moving-тегами
  через GitHub API (текущие `@v4`/`@v5`/`@v2` резолвятся в те же commit), то есть это
  не апгрейд версий, а фиксация уже действующих.
- Решения §7.2/§7.3: Actions **пиним SHA сейчас** (бампы приезжают PR'ом dependabot —
  ecosystem `github-actions` уже настроен); SBOM/provenance — **backlog** (уровень
  зрелости ниже текущих гейтов). `commitlint`/branch protection — **не вводим** ни в
  W5/`088`, ни в backlog (решение владельца, 2026-09-30; записано в `088`).
- **DoD:** правило + lock-гейт + обновлённый `020` + негативные тесты гейта
  (`tests/unit/test_ci_security_gates.py`: mutable-тег, SHA без версии, неканонический
  регистр, локальный composite, реальные workflow, разбор триаж-файла). ✔

### W3 — Производительность · **DONE (2026-09-30)**
- Создано правило `080-performance` (владелец темы: async-блокировки, N+1, пагинация,
  кэш, ресурсы, алгоритмы, гейты); `015` — таблица ratchet дополнена `PERF` и ссылкой
  на владельца; `050` — строки про кэш/ресурсы/N+1 ссылаются на `080`, а не на «план»;
  `099` — индекс и раздел нагрузочных тестов обновлены.
- `ASYNC` **уже включён** (W1, без `per-file-ignores`) — отдельного «жёсткого включения»
  не потребовалось; `PERF` также уже в `select`.
- Пагинация: границы вынесены из роутера в `core/types/pagination.py`
  (`PAGE_LIMIT_DEFAULT=50`, `PAGE_LIMIT_MAX=200`) — 4 копии литералов в
  `presentation/api/routers/sessions.py` заменены на константы (010/080);
  контракт закреплён `tests/unit/test_sessions_pagination.py` (потолок принимается,
  `потолок+1` → 422, неположительный `limit`/отрицательный `offset` → 422).
- Маркер `slow` зарегистрирован в `pyproject.toml`; `scripts/ci_quality.py` исключает
  его из PR-пути (`-m "not live and not llm_live and not slow"`); запуск —
  `make perf` и `.github/workflows/perf-nightly.yml`.
- Нагрузочный тест `tests/perf/test_hot_path_scaling.py`: гейт ловит **алгоритмическую**
  деградацию hot-path, а не «медленную машину».
  - **Метод — счёт инструкций байткода** (`sys.monitoring.INSTRUCTION`), а не время:
    wall-clock дал 12x «регрессию» на линейной функции (занятый раннер), а
    `time.process_time` на Windows имеет гранулярность ~16 мс и измерял ноль.
    Счёт инструкций детерминирован (тот же вход → тот же результат на любой ОС).
  - Проверяется суперлинейность на dedupe диалога, hybrid-merge памяти и token-учёте;
    отдельный тест доказывает, что гейт **падает** на настоящем O(n²) и молчит на
    линейном коде (иначе зелёный гейт ничего не значит).
  - Ограничение метода зафиксировано в правиле: счёт видит Python-уровень, не C
    (`sorted`/`len`), поэтому «суб-линейный» результат для token-учёта — ожидаемое
    поведение, а не пропуск.
- Закрыт перенос из W1: `docs/runbook.md` — `poetry run mypy .` →
  `mypy --strict src/palatium_ai` + команды PR-тестов и нагрузочного гейта.
- `BLE` для `application/`/`infrastructure/` не сужен в этой волне (42 граничных
  broad-catch требуют причины на каждом сайте по 035 — это отдельная работа, 055):
  долг записан явным `TODO(...)` в `pyproject.toml`, `035` приведён в соответствие,
  строка добавлена в §5.
- **DoD:** правило + `ASYNC` + perf-тест. ✔ (`make perf` — 5 passed; `pytest tests
  -m "not live and not llm_live and not slow"` — 5 deselected)

### W4 — Frontend · **DONE (2026-09-30)**
- Новое `084`; `web/package.json` scripts (`lint`, `format:check`, `test`, агрегат
  `verify`); CI-job `frontend`; unit/component/integration-тесты (Vitest + RTL + MSW).
- **DoD:** CI-job зелёный, правило, smoke-тест. ✔ (`npm run verify` — typecheck + lint
  (0 warnings) + prettier + 80 tests; `build:widget` 142.44/150 KiB gzip; `cem:check` ✔)
- **Дрейф, снятый волной (важно для истории):** план считал ESLint/Prettier «уже
  настроенными, но не запускаемыми» — фактически `web/eslint.config.js` и `.prettierrc`
  лежали без зависимостей и без скриптов, то есть гейта не было вовсе. Вместе с этим
  исправлено: правила `react-hooks` были импортированы, но не включены (cleanup
  эффектов не проверялся); 27 файлов приведены к Prettier; `custom-elements.json`
  в индексе отставал от исходника (событие `sed:thread-changed`) — `cem:check` падал.
- **Решение по версии линтера:** ESLint 10 (не 9). `eslint-plugin-react` и
  `eslint-plugin-jsx-a11y` держат peer `^9`, ESLint 9 снят с поддержки → React-правила
  взяты из `@eslint-react/eslint-plugin`. Статический a11y-линт остаётся пробелом
  (закрыт axe в E2E) — запись в §7/backlog.

### W5 — Delivery, документация, git · **DONE (2026-09-30)**
- Новые правила `082` (образы/compose/окружения/миграции/гейты), `086` (docs-as-code,
  OpenAPI, комментарии, долги, ADR), `088` (ветки/коммиты/PR/ревью/CODEOWNERS).
- `scripts/check_todos.py` + `tests/unit/test_check_todos_gate.py` (19 тестов): формат
  `MARKER(owner, ticket, date): …` — блокирующий; тикет-путь **проверяется на
  существование** (мёртвая ссылка на план роняет гейт, «later»/«потом» не принимаются);
  дата в будущем отклоняется; возраст > 180 дней — отчёт, не блок (`--fail-on-stale` —
  опция, иначе гейт лечится поднятием даты). Подключён в `ci_quality.py` и pre-commit.
- Шаблон PR `.github/pull_request_template.md`; `.github/CODEOWNERS` (владельцы путей:
  правила/планы/скиллы, контракт виджета, доставка, `security/`).
- **Перенос из W2 закрыт:** базовый образ `Dockerfile` и `mcp_servers/Dockerfile` — пин по
  digest (`python:${PYTHON_VERSION}-slim@sha256:51dafde…`, 3.14.7-slim-trixie). Дрейф
  роняет CI: новый шаг «base image pin drift» в `scripts/ci_security.py`
  (+5 тестов в `tests/unit/test_ci_security_gates.py`), TODO из правила `025` снят.
- **Сверх плана (найденное при выполнении, а не расширение scope):**
  - CI-job `compose`: `docker compose config --quiet` по базе + оверлеям вложений под
    профилями. Обязательные `${VAR:?}` подставляются подставными значениями **внутри
    шага** (проверяется структура и интерполяция, не доступы) — до этого поломка compose
    обнаруживалась только человеком на `make up`.
  - `.gitignore`: `**/.env` для вложенных деревьев. В скопированном legacy-дереве
    `mcp_servers/edms/edms-ai-assistant/` лежит `.env`, а его собственный `.gitignore`
    держит `.env` закомментированным — файл был одновременно untracked и **не** ignored,
    то есть обычный `git add .` застейджил бы живые креды. Шаблоны `*.example` остаются
    отслеживаемыми; чужой `.gitignore` не правился (017).
  - Долг `feedback.py` («сохранить feedback в БД») оформлен как запись
    `TODO(platform/backend, plans/web-embed-assistant §5 п.17, …)`, а сам пункт добавлен
    в §5 продуктового плана: иначе гейт требовал бы либо выдуманного тикета, либо
    удаления долга из кода.
- **DoD:** правила + гейты + шаблон PR. ✔ (`ci_quality` — PASS, `ci_security` — PASS,
  `pytest tests/unit/test_check_todos_gate.py tests/unit/test_ci_security_gates.py` — 35 passed)
- **Отклонение от плана (осознанное):** CODEOWNERS **не** содержит паттерна по
  `mcp_servers/edms/JavaEdms/**`: это локальный checkout СЭД (в `.gitignore`), и паттерн по
  неотслеживаемому пути не срабатывает никогда. Защита — сам `.gitignore` + правило `090`;
  строка-призрак в CODEOWNERS выглядела бы как защита, не будучи ею.

### W6 — Spec-Driven Development · **DONE (2026-09-30)**
- Новое `005-spec-driven-development.mdc`: когда спецификация обязательна (многофайловая
  работа, новое правило/агент/tool/MCP-инструмент, смена публичного контракта или оси
  политики), где она живёт (`.cursor/plans/<тема>.md` или issue), обязательные разделы
  (в т.ч. **вне scope** — границы против расползания), правило «один PR = одна спека».
- Обобщён уже существовавший прецедент «норма побеждает черновик/чат» (`070`, `092`);
  исключение — только явное подтверждение владельца с пометкой на месте (055/050).
- **DoD:** правило + связка с шаблоном PR и ревью (088). ✔ (шаблон ссылается на
  спеку/правило; 088 требует основание для PR, меняющего поведение под нормой)
- **Честно о гейте:** автоматической проверки «спецификация существует» нет — это ревью
  по 088; так и записано в `005` и `086`, чтобы отсутствие автоматизации не выглядело гейтом.

---

## 5. Backlog гейтов (код/инфраструктура)

| Гейт | Файл | Волна |
|---|---|---|
| ruff ratchet (`DTZ,T20,BLE,ASYNC,PERF,PT,RUF,RET,PIE,FURB,ERA,PTH,TID`) | `pyproject.toml` | W1 (+`PERF` проверен в W3) |
| нагрузочный гейт сложности (`tests/perf/`, маркер `slow`) | `tests/perf/` + `Makefile` (`make perf`) + `.github/workflows/perf-nightly.yml` | W3 ✔ |
| пагинация: потолок из `core/types/pagination.py` + контракт-тест | `src/palatium_ai/core/types/pagination.py`, `tests/unit/test_sessions_pagination.py` | W3 ✔ |
| сужение `BLE001` по сайтам (application/infrastructure, 42 сайта) | `pyproject.toml` + `.py` сайтов | backlog (после W6) |
| `poetry check --lock` | `scripts/ci_security.py` | W2 ✔ |
| pin-drift GitHub Actions (`uses:` без SHA/версии) | `scripts/ci_security.py` + `tests/unit/test_ci_security_gates.py` | W2 ✔ |
| frontend CI-job (tsc/eslint/prettier/vitest/build/e2e) | `.github/workflows/ci.yml` (`npm run verify`), `web/package.json` | W4 ✔ |
| TODO-сканер (`MARKER(owner, ticket, date)`, проверка тикет-пути) | `scripts/check_todos.py` + `scripts/ci_quality.py` + `.pre-commit-config.yaml` | W5 ✔ |
| шаблон PR | `.github/pull_request_template.md` | W5 ✔ |
| CODEOWNERS (`.cursor/rules|plans|skills`, доставка, `security/`; JavaEdms — см. W5) | `.github/CODEOWNERS` | W5 ✔ |
| pin-drift base image (`FROM` без `@sha256:`) | `scripts/ci_security.py` + `tests/unit/test_ci_security_gates.py` | W5 ✔ |
| compose-валидация в CI (структура + интерполяция `${VAR:?}`) | `.github/workflows/ci.yml` (job `compose`) | W5 ✔ |
| статический a11y-линт (`jsx-a11y` несовместим с ESLint 10) | `web/eslint.config.js` | backlog (ждать peer `^10`; покрыто axe в E2E) |
| frontend `afterFileEdit`-хук (eslint --fix + prettier на файл) | `.cursor/hooks.json` + `.cursor/hooks/frontend-quality-gate.sh` | backlog (в W4 решено не вводить: хук не проверен в реальном событии Cursor, а `npm run verify` + CI уже закрывают гейт) |
| SBOM/provenance | CI | backlog (§7) |
| commitlint | — | **отклонено** (решение пользователя, 2026-09-30 · §7.2) |
| `no-commit-to-branch` / branch protection | — | **отклонено** (решение пользователя, 2026-09-30 · §7.2) |

> Замечание: `ci_quality.py` уже прогоняет `ruff format --check` и импорт-слои;
> не дублировать эти проверки в новых гейтах (050).

---

## 6. Guardrails против дублирования (важно)

Таблица «тема → единственный владелец». Новый запрет идёт **в 050** или в своего
владельца, но не в третий файл.

| Тема | Владелец |
|---|---|
| Слои, SRP, реестр агентов | `000` |
| Типы, `Any`, Literal | `010` |
| Стиль, сложность, DRY/KISS/YAGNI, docstrings | `015` (new) |
| Безопасность, HITL, RBAC, секреты, OWASP | `020` |
| Supply chain, lock, образы | `025` (new) |
| Контракты агентов, confidence | `030` |
| Обработка ошибок, fail-closed | `035` (new) |
| Observability, метрики, audit | `040` |
| Таблица антипаттернов | `050` |
| Принципы фиксов | `055` |
| Память | `060` |
| Контекст/оркестрация | `065` |
| MCP-инструменты | `070` |
| Тесты/эвалы | `075` |
| Производительность, данные | `080` (new) |
| Delivery/DevOps | `082` (new) |
| Frontend | `084` (new) |
| Документация, TODO | `086` (new) |
| Git/PR | `088` (new) |
| JavaEdms reference | `090` |
| EDMS-adapter | `092` |
| Карта/индекс | `099` |
| SDD-процесс | `005` (new) |

---

## 7. Открытые вопросы (нужны решения пользователя)

**Зафиксировано:**
- **Ruff ratchet (W1) — полный набор:** `DTZ` + `T20` + `BLE` + `ASYNC` включаются
  сразу, легаси-исключения закрываются через `per-file-ignores`, затем ratchet снимается.
- **Нагрузочный гейт (W3) — счёт инструкций, не время:** пороги латентности в PR-CI
  запрещены (080) — измерялась бы машина, а не код; сложность hot-path пинится
  `sys.monitoring.INSTRUCTION` в `tests/perf/` под маркером `slow`.
- **Фронтенд-линтер (W4) — ESLint 10 + `@eslint-react`:** `eslint-plugin-react` и
  `eslint-plugin-jsx-a11y` держат peer `^9`, ESLint 9 снят с поддержки; ставить 10
  поверх `^9` через `--legacy-peer-deps` запрещено (025). Статический a11y-линт —
  известный пробел, закрыт axe в Playwright, ждёт peer `^10` (backlog §5).
- **Долги и поставка (W5) — решения, принятые при выполнении:**
  - возраст маркера **не** блокирует гейт (отчёт + `--fail-on-stale` по желанию):
    блокирующий возраст лечится правкой даты или удалением строки, оба исхода хуже
    видимого счёта (записано в `086` и в докстроке скрипта);
  - комментарий **Markdown вне области сканера**: в прозе слово-маркер — часть
    документации (включая правило, которое описывает формат), а долг живёт рядом с кодом;
  - compose в CI проверяется с подставными секретами **внутри шага** — проверяем структуру
    и интерполяцию, а не доступы; реальные значения не становятся значениями по умолчанию (082);
  - `.gitignore` получил `**/.env`: во вложенном legacy-дереве `.env` был untracked и
    **не** ignored (его собственный `.gitignore` держит строку закомментированной) —
    это класс бага, который уже упомянут в шапке файла;
  - CODEOWNERS не паттернит `JavaEdms/**` (локальный checkout, `.gitignore`) — rationale в §3.9/W5.

**Открыто:**
1. **`ty`**: добавлять как необязательный быстрый локальный type-check (не гейт) или
   не трогать, пока не выйдет stable?
2. **Actions pin by SHA + commitlint + branch protection**: Actions — **закрыто в W2**
   (2026-09-30): сторонние action пинятся по commit SHA с комментарием версии, дрейф
   ловит `scripts/ci_security.py`. `commitlint` и branch protection — **отклонены**
   (решение пользователя, 2026-09-30): не вводим ни в W5/`088`, ни в backlog.
   Гейт на сообщения коммитов и запрет прямого push в защищённую ветку остаются
   настройкой репозитория, а не правилом/скриптом проекта.
3. **SBOM/provenance**: **закрыто в W2** (2026-09-30) — backlog до релиза: уровень
   зрелости ниже текущих гейтов, а гейт без реальной проверки = шум (§0.2).
4. **Целевые покрытия**: global coverage floor (`PALATIUM_COV_MIN_GLOBAL`) и целевой
   % frontend-тестов — какие числа фиксируем?
5. **IaC/GitOps**: выбираем инструмент (Argo CD / Terraform / Pulumi) или остаёмся
   на compose + workflow до отдельного решения?

---

## Приложение A — Переработанный черновик (нормализованный, исправленный)

Ниже — тот же черновик, но приведённый к фактам и к терминологии проекта. Это
**не** правило; после волн его содержание живёт в правилах из §3.

**1. Архитектура и структура.** Гексагональные слои и правила импортов — `000`.
SOLID/DRY/KISS/YAGNI — `015`. Антипаттерны (в т.ч. God Agent, «vibe coding» без
spec) — `050` + `005`. Масштабируемость — async/параллелизм (`080`), CQRS/Event
Sourcing **не** вводить без явной необходимости (YAGNI). Spec-Driven Development —
`005`.

**2. Качество кода.** Ruff — единственный линтер/форматтер (`015`). Сложность ≤ 10,
вложенность ≤ 3, длина функции — ориентир ≤ 50 (`015`). Дублирование — `015`/`050`.
Строгая типизация — `010`; **mypy --strict**, не Ty (beta).

**3. Безопасность.** OWASP Top 10:2025 — маппинг в `020`; A01 (AC везде,
deny-by-default), A02 (misconfig), A03 (supply chain → `025`), A10 (исключения →
`035`). Секреты/валидация/параметризованные запросы/RBAC — `020`/`070` (не дублировать).

**4. Производительность.** Блокирующий I/O в async, N+1, пагинация, кэш с TTL,
утечки, сложность — `080`. Числа «85–87% / 700–860%» — убраны как непроверенные.

**5. Testing и QA.** Пирамида 60–75/20–30/5–10 — `075`; frontend (Vitest/RTL/MSW/
Playwright) — `084`; evals/baseline — `075`.

**6. DevOps и CI/CD.** Multi-stage, digest, non-root — `082`; Prometheus/Grafana/
Loki — `040` и `deploy/observability` (ссылка, без дубля); IaC/GitOps — открытый
вопрос §7.

**7. Документация.** docs-as-code, OpenAPI из Pydantic, комментарии «почему»,
TODO с owner — `086`.

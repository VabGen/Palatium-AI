# Palatium AI — полный гайд

От клонирования репозитория до запуска, API, Docker, секретов, разработки и эксплуатации.

> Краткая «витрина» продукта: [`../README.md`](../README.md)  
> Индекс docs: [`README.md`](README.md)  
> Этот файл — рабочая документация для тех, кто уже решил ставить и использовать платформу.

---

## Оглавление

1. [Нужно ли вам это](#1-нужно-ли-вам-это)
2. [Требования](#2-требования)
3. [Клонирование](#3-клонирование)
4. [Конфигурация окружения](#4-конфигурация-окружения)
5. [Запуск локально (Poetry)](#5-запуск-локально-poetry)
6. [Запуск в Docker](#6-запуск-в-docker)
7. [MCP stubs для разработки](#7-mcp-stubs-для-разработки)
8. [Проверка и первое использование API](#8-проверка-и-первое-использование-api)
9. [Контракт API](#9-контракт-api)
10. [Архитектура и runtime workflow](#10-архитектура-и-runtime-workflow)
11. [MCP, LLM и инструменты](#11-mcp-llm-и-инструменты)
12. [Security & Observability](#12-security--observability)
13. [Отладка в VS Code](#13-отладка-в-vs-code)
14. [Разработка и проверки](#14-разработка-и-проверки)
15. [Retention MCP tool calls](#15-retention-mcp-tool-calls)
16. [Секреты, CI, Vault](#16-секреты-ci-vault)
17. [Карта кода](#17-карта-кода)
18. [Документы в `docs/`](#18-документы-в-docs)

---

## 1. Нужно ли вам это

**Palatium AI** — production-oriented платформа multi-agent ассистентов:

- оркестрация через **LangGraph** (Contextualizer → Intent → Supervisor → ContextWeaver → Worker → Critic → Formatter);
- инструменты через **MCP** (JSON-RPC 2.0) с **RBAC allow-list**;
- **Zero Trust + HITL** (`requires_review`, audit, confidence gates);
- единый LLM-слой через **LiteLLM** (OpenAI / Anthropic / Ollama / Qwen…).

Подходит, если вы строите офисного/корпоративного ассистента с контролируемыми tool-вызовами (СЭД, analytics и т.д.).

Не подходит как «чат-виджет на 5 минут» без БД/Redis/LLM — это полноценный backend.

---

## 2. Требования

| Компонент | Версия / заметка |
|-----------|------------------|
| Git | любой актуальный |
| Python | **3.14** (`>=3.14,<3.15`) |
| Poetry | 2.x |
| PostgreSQL | локально или remote |
| Redis | локально или remote |
| LLM | Ollama local/cloud, OpenAI и др. (см. `env/`) |
| Docker Desktop | опционально, для контейнерного запуска |
| (опц.) MCP stubs | `scripts/dev-up.ps1` → `:8080`, `:8081` |

---

## 3. Клонирование

```bash
git clone https://github.com/your-org/palatium-ai.git
cd palatium-ai
```

Windows (PowerShell):

```powershell
git clone https://github.com/your-org/palatium-ai.git
cd palatium-ai
```

Установите зависимости Python:

```bash
poetry install --with dev
```

---

## 4. Конфигурация окружения

### 4.1. Создать рабочий `.env`

```powershell
# канонический шаблон
Copy-Item env\.env.example env\.env

# или готовый профиль:
Copy-Item env\.env.local.example env\.env   # Ollama local
# Copy-Item env\.env.cloud.example env\.env # OpenAI cloud
```

Заполните минимум:

- `POSTGRES_*`, `REDIS_*`
- `LLM_DEFAULT_PROVIDER` + ключи выбранного провайдера
- `EMBEDDING_DEFAULT_PROVIDER` + ключи
- `MCP_SERVERS` (если нужны tools)

### 4.2. Профили файлов

| Файл | Назначение | Типичный `LOG_LEVEL` |
|------|------------|----------------------|
| `env/.env` | рабочий default (gitignore) | ваш `LOG_LEVEL` |
| `env/.env.dev` | отладка агентов | DEBUG |
| `env/.env.staging` / `.prod` | локальные каркасы (gitignore) | INFO/WARNING + JSON |
| `env/.env.example` | **канон** всех переменных + чеклист админа | — |
| `env/.env.local.example` | Ollama local | DEBUG |
| `env/.env.cloud.example` | OpenAI | INFO |
| `env/.env.staging.example` / `.prod.example` | деплой-каркасы без секретов | — |

Выбор файла:

```powershell
$env:ENV_FILE = "env/.env.dev"
poetry run python -m palatium_ai.main
```

По умолчанию приложение читает `env/.env` (см. `BaseConfig`).

Секреты (`env/.env`, `.env.dev`, …) в `.gitignore`. Схема Vault/CI: [`secrets.md`](secrets.md).

---

## 5. Запуск локально (Poetry)

### 5.1. Миграции БД

```bash
poetry run alembic upgrade head
```

### 5.2. Старт API

```bash
# вариант A
poetry run python -m palatium_ai.main

# вариант B
poetry run uvicorn palatium_ai.main:app --reload --host 127.0.0.1 --port 8000
```

API: http://127.0.0.1:8000  
Swagger: http://127.0.0.1:8000/docs  
Health: http://127.0.0.1:8000/health

### 5.3. Логи агентов

- `LOG_LEVEL=INFO` — без подробной цепочки узлов  
- `LOG_LEVEL=DEBUG` — `agent.node.start` / `agent.node.end` / `agent.llm_call`

Используйте `env/.env.dev` или Debug-конфиг VS Code «development».

---

## 6. Запуск в Docker

Полная пошаговая инструкция: **[`docker.md`](docker.md)**.

Полный стек (Postgres + Redis + Neo4j + MCP + API):

```powershell
docker compose --env-file env/.env up --build
```

Только API-образ (зависимости на хосте):

```powershell
docker build -t palatium-ai:local .

docker run --rm -p 8000:8000 `
  --env-file env/.env `
  -e POSTGRES_HOST=host.docker.internal `
  -e REDIS_HOST=host.docker.internal `
  -e APP_HOST=0.0.0.0 `
  palatium-ai:local
```

> В контейнере `localhost` ≠ хост. В Compose используйте DNS-имена сервисов (`postgres`, `redis`, `neo4j`).

---

## 7. MCP stubs для разработки

### Вариант A — Docker Compose (рекомендуется с API в Docker)

Корневой [`docker-compose.yml`](../docker-compose.yml) поднимает `mcp-edms` и `mcp-analytics` вместе с API.  
Dockerfile stubs: [`mcp_servers/Dockerfile`](../mcp_servers/Dockerfile).

### Вариант B — на хосте (Poetry)

```powershell
.\scripts\dev-up.ps1    # EDMS :8080, Analytics :8081 (+ опционально API)
.\scripts\dev-down.ps1
```

Проверка Bearer на stubs (после `dev-up` или Compose):

```powershell
$env:MCP_AUTH_TOKEN = "dev-mcp-local-token"
poetry run python scripts/smoke_mcp_auth.py --skip-api
poetry run python scripts/smoke_mcp_registry.py
poetry run python scripts/smoke_mcp_turn.py
```

В `MCP_SERVERS` для локального Poetry:

```json
{"edms":"http://localhost:8080","analytics":"http://localhost:8081"}
```

Если API в Docker, а stubs на хосте:

```json
{"edms":"http://host.docker.internal:8080","analytics":"http://host.docker.internal:8081"}
```

Справочник СЭД «Канцлер NEXT» (`mcp_servers/edms/JavaEdms/`) — **только чтение**, не runtime.

---

## 8. Проверка и первое использование API

### Health

```bash
curl http://127.0.0.1:8000/health
```

### Classify intent

```bash
curl -X POST "http://127.0.0.1:8000/api/intents/classify" \
  -H "Content-Type: application/json" \
  -d '{ "text": "Find the EDMS contract", "thread_id": "thread-1" }'
```

### Полный пайплайн (process → Formatter)

```bash
curl -X POST "http://127.0.0.1:8000/api/intents/process" \
  -H "Content-Type: application/json" \
  -d '{ "text": "Schedule a meeting with the team tomorrow", "thread_id": "thread-2" }'
```

### Sessions

- `GET /api/sessions/` — список
- `POST /api/sessions/` — upsert по `thread_id`
- `GET /api/sessions/{thread_id}` — одна сессия
- `GET /api/sessions/{thread_id}/turns` — transcript (DialogTurn, last N)
- `GET /api/sessions/{thread_id}/mcp-tool-calls` — MCP calls
- `GET /api/sessions/{thread_id}/timeline` — session + trace

### Agents (stub)

- `GET /api/agents/`
- `GET /api/agents/health`

Удобнее всего — Swagger UI: http://127.0.0.1:8000/docs

---

## 9. Контракт API

Ответы — Pydantic-модели домена (`IntentTaskResult`, `FormatterTaskResult`, …).

### `POST /api/intents/classify`

**Request** (`ClassifyIntentRequest`)

| Поле | Тип | Ограничения |
|------|-----|-------------|
| `text` | string | 1…32000 |
| `thread_id` | string | 1…128 |

**Response** (`IntentTaskResult`)

| Поле | Тип |
|------|-----|
| `task_id` | string |
| `agent_role` | string |
| `status` | `success` \| `failure` \| `partial` |
| `confidence` | 0.0…1.0 |
| `requires_review` | boolean |
| `error` | string \| null |
| `output` | `IntentClassifierOutput` \| null |

`IntentClassifierOutput`:

- `task_kind`: `capability_discovery` \| `knowledge_request` \| `multi_step_workflow` \| `tool_execution` \| `response_formatting` \| `clarification_needed`
- `requires_mcp`: boolean
- `candidate_capabilities`: string[]
- `confidence`: number
- `reasoning`: string

### `POST /api/intents/process`

Тот же request. Response — `FormatterTaskResult` с `output` = **ContentDocument**
(`domain/content`, не агентский пакет: `schema_version`, `locale`, `title`, `blocks[]`,
`actions[]`, `meta`). Блоки — typed union (`heading`, `list`, `table`, `steps`, …);
markdown-fallback поля нет.

### Chat UI (structured renderer)

Клиент рендерит `blocks[]` + icon tokens (Lucide), не markdown.

```powershell
# API (терминал 1)
poetry run python -m palatium_ai.main

# UI (терминал 2)
cd web
npm install
npm run dev
# → http://127.0.0.1:5173/ui/
```

Сборка в API на `/ui`:

```powershell
cd web
npm install
npm run build
# перезапуск API → http://127.0.0.1:8000/ui/
```

### HITL

При `requires_review=true` или approval для write/unknown MCP сервер создаёт карточку
(`hitl_cards[]` в ответе process): `card_id`, TTL 5–30 мин, кликабельные options с
**HMAC `action_token` v2** (привязка к `card|action|exp|subject|nonce`).

`POST /api/hitl/{card_id}/respond` (JWT owner thread):

```json
{"action_id":"approve","action_token":"<from option>","idempotency_key":"...","step_up_assertion":"<optional>"}
```

- Повтор с тем же `idempotency_key` — replay.
- Токены **не** пишутся в dialog history; UI гидратирует через `GET /api/hitl/{id}` только `pending`.
- High-risk `mcp_tool_approval` (`risk_score ≥ 0.7`) in staging/prod требует
  `POST /api/hitl/{id}/step-up-challenge` → `step_up_assertion` на respond.
  - Local: `HITL_STEP_UP_METHOD=hmac_stub` (pre-minted HMAC assertion).
  - Staging/prod: `idp_acr` или `webauthn` — IdP JWT с `acr` ∈ allow-list,
    claim `HITL_STEP_UP_CARD_CLAIM` (=card_id), optional `amr` (для `webauthn`
    по умолчанию требуется `webauthn`). HMAC stub в staging/prod **запрещён**.
  - Опционально `HITL_STEP_UP_AUTHORIZE_URL` — шаблон старта IdP
    (`{card_id},{subject},{challenge},{required_acr},{card_claim},{method}`);
    UI открывает URL (`return_origin`) и принимает `postMessage`
    `{type:"palatium.hitl.step_up",assertion}` только с origin шаблона;
    paste JWT — fallback. В **development** доступен stub
    `GET /api/auth/dev-hitl-step-up` (+ JSON `Accept: application/json`).
  - Dev smoke без LLM: `POST /api/hitl/dev/mint-tool-approval` →
    `scripts/smoke_hitl_write_step_up.py`.
- Просрочка с `risk_score > 0.5` → **escalate** (manager queue + OOB notify:
  logging + optional webhook / SMTP email / Slack bot) + audit
  `hitl_escalation_notified`; иначе `auto_rejected`.
- Manager: `GET /api/hitl/queue/escalated` (tenant `org_id`), `POST .../manager-resolve`.

Write MCP (EDMS stub): `archive_document` — platform-pinned `write` → HITL interrupt
до вызова (self-attestation сервера не снижает риск).
Хранилище HITL: **Redis** (in-memory запрещён в staging/production).
Фоновый TTL sweep раз в 60с закрывает просроченные pending-карточки (CAS, не затирает resolve).

#### Underspecification → HITL choice

| `underspecification_kind` | Поведение |
|---------------------------|-----------|
| `none` | обычный turn |
| `discrete_choice` | incomplete discrete slot → `requires_user_choice` + clarify; если Formatter не дал `actions`, `OptionSynthesizer` синтезирует 2–12 options → HITL cards |
| `open_text` | свободное уточнение текстом, **без** fake-меню |

Пример класса (не phrase-list): «сделай X на тему/типа/в формате» без значения слота → карточки на **первом** ходе.

| ID | Сценарий | Покрытие |
|----|----------|----------|
| S1/S3 | Exclusive menu без Intent flag → cards | `test_hitl_scenario_matrix` + assembler |
| S2 | Click → typed `HITL_CHOICE_RESUME` | choice_resume + matrix |
| S4 | Required choice без options → fail-closed | matrix |
| S5–S7 | write HITL / unknown HITL / read no HITL | tool_policy + matrix |
| S8 | Choice axis → clarification before tools | UserChoiceIntent + Continuity |
| S9 | TTL risk>0.5 → escalate | escalation_policy |
| S10 | Idempotent respond replay | `test_hitl_service` |

Live smoke (API up): `scripts/smoke_hitl_choice.py`, `scripts/smoke_hitl_write_step_up.py`.

#### MCP tool onboarding checklist

При добавлении MCP-сервера / tool (код > attestation сервера):

1. Stub/server: tool + `inputSchema` (JSON Schema 2020-12).
2. Platform pin в `domain/mcp/tool_policy.py` → `_PLATFORM_SIDE_EFFECTS`:
   - ключ `mcp:<server>.<tool>`;
   - `side_effect`: `read` | `write`;
   - `schema_fingerprint` от **канонической** схемы (должна байт-в-байт совпасть
     с discovered `inputSchema`, иначе demote → `unknown` + HITL);
   - `risk_tier`: `low` | `medium` | `high`;
   - `requires_hitl`: явный bool (`write`/`high` обычно `true`; `read`/`low` — `false`).
3. Researcher ACL: `mcp:<server>.<tool>` в `RESEARCHER_CONFIG.allowed_tools`.
4. `MCP_SERVERS` / Consul URL для сервера.
5. Smoke: read без карточки; write/unknown → `mcp_tool_approval` card (+ step-up если risk≥0.7).

Без pin: `side_effect=unknown`, `requires_hitl=true` (fail-closed). Capability index
прокидывает эти поля в `MCPCapabilityBinding` при discover.

#### Escalation lifecycle / dead-letter SLA

| Состояние | Кто действует | SLA |
|-----------|---------------|-----|
| `pending` | owner | TTL 5–30 мин |
| `escalated` | manager (same org) | новый TTL после escalate; queue + OOB notify |
| `resolved` | — | terminal; idempotent replay only |
| `auto_rejected` | — | terminal low-risk timeout |
| `dead_letter` | ops | manager TTL истёк без resolve — **без** повторного escalate; audit `hitl_card_dead_letter` + OOB; метрика `hitl_dead_letter`; lazy close на GET/`list_escalated` и TTL sweep |

### Observability / ops

| Endpoint / knob | Назначение |
|-----------------|------------|
| `GET /health` | liveness |
| `GET /metrics` | Prometheus scrape (без JWT) |
| `POST /api/admin/kill-switch/*` | аварийный стоп (admin role) |
| `LLM_FALLBACK_PROVIDERS` | ordered LiteLLM fallback ≥2 |
| `TURN_COST_BUDGET_USD` / `DAILY_COST_BUDGET_USD` | hard cost caps (`0` = off) |

SLA gate scripts (offline unit + optional live): `scripts/run_sla_gates.py`.
Live LLM sample (opt-in, burns tokens): `scripts/eval_api_live.py`.
Ops checklist before staging/prod: [`ops-readiness.md`](ops-readiness.md).

### PDF export

`POST /api/documents/export/pdf` — body = `ContentDocument` (тот же `output` из process).
В chat UI кнопка **PDF** на каждом ответе ассистента.

### Sessions / MCP calls

См. модели `SessionResponse`, `McpToolCallResponse`, `SessionTimelineResponse` в коде `presentation` / `domain`. Query-параметры списков: `limit`, `offset`, фильтры `event`, `is_error`, `server_name`, `include_archived`.

---

## 10. Архитектура и runtime workflow

### Слои (Clean / Hexagonal)

| Слой | Путь | Ответственность |
|------|------|-----------------|
| Domain | `src/palatium_ai/domain/` | контракты агентов, инварианты |
| Application | `src/palatium_ai/application/` | use-cases, LangGraph, planners |
| Infrastructure | `src/palatium_ai/infrastructure/` | LiteLLM, MCP, Postgres, Redis |
| Presentation | `src/palatium_ai/presentation/` | FastAPI |

### Runtime workflow

1. API → `IntentService.classify` / `process`
2. Persist user DialogTurn → load last-K prior turns
3. LangGraph (`thread_id:task_id` checkpointer):
   - `Contextualizer` → `IntentClassifier` → `Supervisor` → `ContextWeaver` → (`Researcher`?) → `Critic` → `Formatter`
4. При `requires_mcp=true` — capability resolution, schema-driven args, MCP tool call (RBAC).
5. Persist assistant DialogTurn; return Formatter result

Платформенный реестр агентов (12 ролей) — в правилах архитектуры; в текущем графе: contextualizer (роль text_ingestor) / classifier / supervisor / context_weaver / researcher / critic / formatter.

### Память (spine)

| Слой | Сейчас | Дальше |
|------|--------|--------|
| DialogTurn last-K | Postgres `dialog_turns` + `GET .../turns` | — |
| Contextualizer | rewrite/continuation до Intent + `MemoryPromptBudget` | — |
| Checkpointer | `MemorySaver` default; `LANGGRAPH_CHECKPOINT_POSTGRES=true` → AsyncPostgresSaver; bake-off `scripts/bakeoff_checkpointer_workers.py` | — |
| MemoryPort | Postgres `memory_items` + FTS GIN; staging `MEMORY_EMBEDDING_RERANK=true` | — |
| Budgeted recall | ≤4 hits / 800 chars, min confidence 0.7, thread+user+org ns | — |
| DialogTurn payload | ContentDocument JSON for rich UI hydrate | — |
| Sleep-time | MemoryKeeper queue (`frontier` / `gpt-oss:120b-cloud`), ADD-only | — |
| Chat UI transcript | localStorage thread/user/org + `GET .../turns` | — |
| Eval gates | offline + live LongMemEval-lite (ACL/anaphora/format/keeper) | corpus growth as needed |
| Graphiti | opt-in `MEMORY_BACKEND=graphiti` → `GraphitiMemoryPort` (Neo4j, `graphiti-core`) | — |
| Mem0 adapter | opt-in `MEMORY_BACKEND=mem0` → `Mem0MemoryPort` (v3 ADD REST) | — |

---

## 11. MCP, LLM и инструменты

- **MCP** — Host инициирует JSON-RPC 2.0 к Server (tools/resources).
- **LiteLLM** — единый адаптер `generate` / `generate_stream` для провайдеров.
- **RBAC** — `AgentConfig.allowed_tools`; вне списка → deny + audit.
- Registry: static `MCP_SERVERS`, файл `MCP_SERVERS_FILE`, или Consul.

---

## 12. Security & Observability

- Zero Trust tool allow-list
- HITL при низком confidence / risky действиях (`requires_review`)
- Hash-chained audit (см. observability rules)
- Метрики узлов / escalation
- Tracing: LangSmith при наличии ключа; иначе structlog fallback
- Логи агентов на `DEBUG`; ошибки узлов — `WARNING`

---

## 13. Отладка в VS Code

Конфиги: [`.vscode/launch.json`](../.vscode/launch.json)

| Конфиг | `ENV_FILE` |
|--------|------------|
| palatium-ai: default | `env/.env` |
| palatium-ai: development | `env/.env.dev` (DEBUG) |
| palatium-ai: staging | `env/.env.staging` |
| palatium-ai: production | `env/.env.prod` |

---

## 14. Разработка и проверки

Полный локальный/CI baseline (ruff + mypy --strict на `src/palatium_ai` + remediation tests + SLA math + PyJWT check):

```powershell
poetry run python scripts/ci_quality.py
```

CI: `.github/workflows/ci.yml` гоняет тот же baseline на push/PR (включая offline 100-task FakeLLM benchmark).

Точечно:

```powershell
poetry run ruff check .
poetry run ruff format .
poetry run mypy --strict src/palatium_ai
poetry run pytest -q
poetry run python scripts/run_sla_gates.py --check-math
```

**Не ставьте** PyPI-пакет `jwt` — только `PyJWT`. Иначе ломается `from jwt import PyJWKClient`.

Cursor hooks (quality / secret-scan) — в `.cursor/hooks/` (`python-quality-gate.sh` гоняет ruff+mypy на изменённых `.py`).

---

## 15. Retention MCP tool calls

Скрипты:

- `scripts/archive_mcp_tool_calls.py` — soft-archive
- `scripts/purge_archived_mcp_tool_calls.py` — физическое удаление архива
- `scripts/mcp_tool_calls_retention_report.py` — отчёт

По умолчанию **dry-run**. Реальное изменение — `MCP_RETENTION_EXECUTE=true` или `--execute`.

```bash
# preview archive
poetry run python scripts/archive_mcp_tool_calls.py --days 90

# execute
poetry run python scripts/archive_mcp_tool_calls.py --days 90 --execute

# purge preview / execute
poetry run python scripts/purge_archived_mcp_tool_calls.py --years 3
poetry run python scripts/purge_archived_mcp_tool_calls.py --years 3 --execute

# report
poetry run python scripts/mcp_tool_calls_retention_report.py --purge-years 3
```

Env для scheduler:

- `MCP_RETENTION_ARCHIVE_DAYS`, `MCP_RETENTION_PURGE_YEARS`, `MCP_RETENTION_BATCH_SIZE`
- `MCP_RETENTION_EVENT`, `MCP_RETENTION_SERVER_NAME`, `MCP_RETENTION_IS_ERROR`
- `MCP_RETENTION_EXECUTE`

Exit codes: `0` ok · `2` config · `3` runtime.

Пример cron / GitHub Actions — в истории репо и в [`secrets.md`](secrets.md) / CI examples.

---

## 16. Секреты, CI, Vault

Полная схема: **[`secrets.md`](secrets.md)**.

Кратко:

1. Локально — `env/.env*` (gitignore).
2. CI — GitHub Actions Secrets → `env:` job.
3. Prod — Vault / K8s Secret → process env; в git только плейсхолдеры.

---

## 17. Карта кода

```
src/palatium_ai/
  domain/           # контракты агентов
  application/      # agents, orchestration (LangGraph), services, tools
  infrastructure/   # llm, mcp, database, cache
  presentation/     # FastAPI routers
  core/             # config, logging, observability
env/                # профили окружения
deploy/             # compose examples
scripts/            # dev-up, retention, docker-entrypoint
mcp_servers/        # MCP stubs (+ JavaEdms reference, read-only)
docs/               # эта документация
Dockerfile          # multi-stage runtime / test / devtools
```

---

## 18. Документы в `docs/`

| Документ | Содержание |
|----------|------------|
| [`handbook.md`](handbook.md) | этот полный гайд |
| [`docker.md`](docker.md) | Docker от А до Я |
| [`secrets.md`](secrets.md) | Vault / CI / Compose secrets |
| [`ops-readiness.md`](ops-readiness.md) | staging/prod чеклист после Weeks 0–8 |
| [`README.md`](README.md) | индекс документации |

---

## Лицензия

MIT — см. корневой [`README.md`](../README.md) и `LICENSE` пакета.

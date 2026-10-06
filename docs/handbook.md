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
6. [Запуск: три режима](#6-запуск-три-режима)
7. [MCP stubs](#7-mcp-stubs)
8. [Проверка и первое использование API](#8-проверка-и-первое-использование-api)
9. [Контракт API](#9-контракт-api)
10. [Архитектура и runtime workflow](#10-архитектура-и-runtime-workflow)
11. [MCP, LLM и инструменты](#11-mcp-llm-и-инструменты)
12. [Security & Observability](#12-security--observability)
13. [Отладка в VS Code](#13-отладка-в-vs-code)
14. [Разработка и проверки](#14-разработка-и-проверки)
15. [Retention](#15-retention)
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

```bash
# --- App DB ---
POSTGRES_USER="postgres"
POSTGRES_PASSWORD="1234"
POSTGRES_DB="postgres"            # ← именно postgres, НЕ palatium_dev
POSTGRES_SCHEMA="palatium_ai"
POSTGRES_PUBLISH_PORT=5432        # 5433, если на хосте уже есть Postgres

# --- Gateway (LiteLLM) ---
LITELLM_MASTER_KEY="sk-palatium-master"
LITELLM_PUBLISH_PORT=4000
PALATIUM_GATEWAY_KEY=""           # сгенерировать: .\scripts\litellm-provision-key.ps1

# --- Провайдер ---
QWEN_API_KEY="corporate-llm"
QWEN_BASE_URL="http://model-generative.shared.du.iba/v1"
QWEN_DEFAULT_MODEL="generative-model"

# --- Прочее ---
EMBEDDING_DEFAULT_PROVIDER="qwen"
MCP_SERVERS='{"edms":"http://localhost:8080","analytics":"http://localhost:8081"}'
```

> **`POSTGRES_DB=postgres`** — все схемы приложения (`palatium_ai`,
> `edms_assistant`, `knowledge`, `memory`) внутри. Отдельная БД нужна только
> для Langfuse (`langfuse`).

Остальные ключи (`REDIS_*`, `LLM_DEFAULT_PROVIDER` и ключи провайдера,
`EMBEDDING_*`) — из `env/.env.example` (там легенда `[MUST-SET]`/`[SECRET]`).

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

## 6. Запуск: три режима

Проект поддерживает **три** режима, которые **нельзя смешивать**
(конфликт по портам 8080/8081/8000):

| Режим | Где MCP | Где API | Gateway | Когда использовать |
|---|---|---|---|---|
| **Host** | Poetry (host) | Poetry (host) | — | Ежедневная разработка (hot-reload) |
| **Docker** | Docker | Docker | — | CI / демо / prod-like |
| **Gateway** | Poetry (host) | Poetry (host) | :8090/8091 | Тест политик MCP |

> **Про `docker compose` ниже.** Команды предполагают, что в `$PROFILE` задано
> `$env:COMPOSE_ENV_FILES = "env/.env"` (см. [`../START.md`](../START.md) §3).
> Без этого Compose не подставит `${POSTGRES_*}` / `${QWEN_*}` и упадёт с
> `POSTGRES_PASSWORD is not set` — тогда добавляйте `--env-file env/.env` вручную.

### 6.1. Host-профиль (рекомендуется для разработки)

```powershell
# 1. Docker только для инфраструктуры
docker compose up -d postgres redis neo4j litellm

# 2. MCP stubs + API через Poetry
.\scripts\dev-up.ps1

# 3. Проверка
.\scripts\dev-status.ps1
```

**Что запустится:**
- API :8000 — Poetry (hot-reload)
- MCP EDMS :8080 — Poetry
- MCP Analytics :8081 — Poetry

**Остановка:** `.\scripts\dev-down.ps1 -Force` — снимает только host-процессы. Если
8080/8081 держат контейнеры (видно по `[skip] ... not a repo process`), Docker не
трогается; `-Force` **не** отменяет эту защиту, для осознанного добивания чужого —
`-AllowForeign` (подробно: [`../START.md`](../START.md) §7).

### 6.2. Docker-профиль

Полный стек в Docker:

```powershell
# Убить host-процессы
.\scripts\dev-down.ps1 -Force

# Поднять всё в Docker
docker compose --profile docker-mcp --profile docker-api up -d --build

# Проверить
docker compose ps
```

> **`docker-compose.override.yml`** отключает MCP/API в Docker по умолчанию —
> они поднимаются только по профилям. Это правильно и защищает от конфликта
> портов с host-профилем.

Полная пошаговая инструкция: [`docker.md`](docker.md).

### 6.3. Gateway-профиль

```powershell
.\scripts\dev-down.ps1 -Force
.\scripts\dev-up.ps1 -WithGateway
```

API ходит на gateway :8090/8091 → gateway проксирует на upstream :8080/:8081.
Нужен для тестирования `pin_allowlist` / `pin_filter` / `upstream_policy`.

**Стартовая инструкция:** [`../START.md`](../START.md) — все 3 режима подробно.

---

## 7. MCP stubs

> Профили и режимы — см. §6. Ниже — оба варианта.

### Вариант A — Host (Poetry) — рекомендуется

```powershell
.\scripts\dev-up.ps1               # API + MCP stubs (direct)
.\scripts\dev-up.ps1 -WithGateway  # + gateway :8090/8091
.\scripts\dev-up.ps1 -SkipApi      # только MCP stubs
.\scripts\dev-down.ps1 -Force
```

### Вариант B — Docker

Корневой [`docker-compose.yml`](../docker-compose.yml) поднимает `mcp-edms` и
`mcp-analytics` вместе с API по профилю `docker-mcp`.
Dockerfile stubs: [`mcp_servers/Dockerfile`](../mcp_servers/Dockerfile).

Проверка Bearer на stubs (после `dev-up` или Compose):

```powershell
$env:MCP_AUTH_TOKEN = "dev-mcp-local-token"
poetry run python scripts/smoke_mcp_auth.py --skip-api
poetry run python scripts/smoke_mcp_registry.py
poetry run python scripts/smoke_mcp_turn.py
```

Stubs **fail-closed**: без `MCP_AUTH_TOKEN` JSON-RPC отклоняется (401),
пока явно не задан `MCP_ALLOW_ANON=1` (только локальный bootstrap, не shared network).
`dev-up.ps1` сам выставляет `dev-mcp-local-token`, если токен не задан.

Progressive disclosure: клиент discovery шлёт `tools/list` с
`omitInputSchema: true`; stubs отвечают карточками (`propertyNames`) без полного
`inputSchema`. Полная schema грузится только на `list_tools` / `get_tool` / call.

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
Off-graph memory: `POST /api/memory/save|forget|extract` → HITL →
`/api/hitl/{id}/respond` (`scripts/smoke_memory_hitl.py`).
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
| Checkpointer | Postgres `AsyncPostgresSaver` in staging/prod (or `LANGGRAPH_CHECKPOINT_POSTGRES=true`); `MemorySaver` in development; dual TTL `MEMORY_SESSION_TTL_SECONDS` + `RETENTION_CHECKPOINT_DAYS`; bake-off `scripts/bakeoff_checkpointer_workers.py` | — |
| MemoryPort | Postgres `memory.entries` + FTS + pgvector; `MEMORY_HYBRID_FUSION`/`MEMORY_RRF_K` + search-time importance; opt-in `MEMORY_EMBEDDING_RERANK` | — |
| Extract / promote | Durable `memory.extract_jobs` (SKIP LOCKED); promote = `python -m palatium_ai.jobs.memory_promote --user-id …` (not from extract) | — |
| Procedural skills (L5) | JIT `skill_catalog` + MCP `skill_reference`; roots `SKILLS_ROOTS` (`skills/procedural`); `.agent/MEMORY.md` = Cursor DX only | — |
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
poetry run pytest -q -m "not live and not llm_live and not slow"
poetry run python scripts/run_sla_gates.py --check-math
```

`slow` — нагрузочный гейт сложности hot-path (счёт инструкций байткода, правило 080):
в PR-путь не входит, но исключён из него явно; запуск — `make perf`
(то же делает `.github/workflows/perf-nightly.yml` nightly).

**Не ставьте** PyPI-пакет `jwt` — только `PyJWT`. Иначе ломается `from jwt import PyJWKClient`.

Cursor hooks (quality / secret-scan) — в `.cursor/hooks/` (`python-quality-gate.sh` гоняет ruff+mypy на изменённых `.py`).

---

## 15. Retention

Полный гайд по платформенному job (окна, классы, CLI, диагностика):
**[`global-retention.md`](global-retention.md)**. ADR —
[`adr/0002-global-retention-scheduler.md`](adr/0002-global-retention-scheduler.md).

### 15.1. Global data retention (CronJob / CLI)

```powershell
poetry run alembic upgrade head   # d4e5f6a7b8c9 + e5f6a7b8c9d0
poetry run python -m palatium_ai.jobs.retention --list-classes
poetry run python -m palatium_ai.jobs.retention   # dry-run всех classes
# poetry run python -m palatium_ai.jobs.retention --execute --class memory_medium
```

- Env: `RETENTION_*` в `env/.env.example` §10b (и ваш `env/.env`).
- Default — dry-run; destructive только `--execute` или `RETENTION_EXECUTE=true`.
- Attachments: global cron = SoT; `POST /api/attachments/sweep` — per-owner defense
  ([`runbook.md`](runbook.md) §16.6 / §17).

### 15.2. MCP tool calls (отдельные скрипты)

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

Пример cron / GitHub Actions — в [`secrets.md`](secrets.md) / CI examples.
Wire в единый оркестратор — волна W5 плана global-retention.

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
| [`../START.md`](../START.md) | стартовая инструкция: setup + `$PROFILE` + 3 режима |
| [`handbook.md`](handbook.md) | этот полный гайд |
| [`docker.md`](docker.md) | Docker от А до Я |
| [`runbook.md`](runbook.md) | операторский runbook: симптомы, фиксы, полный сброс |
| [`secrets.md`](secrets.md) | Vault / CI / Compose secrets |
| [`ops-readiness.md`](ops-readiness.md) | staging/prod чеклист после Weeks 0–8 |
| [`global-retention.md`](global-retention.md) | global retention: `RETENTION_*`, CLI, классы, диагностика |
| [`agent-evals.md`](agent-evals.md) | agent evals: PR baseline / cassette / nightly judge |
| [`../deploy/observability/README.md`](../deploy/observability/README.md) | Prometheus / Grafana / Loki / Alertmanager + SLO |
| [`README.md`](README.md) | индекс документации |

---

## Лицензия

MIT — см. корневой [`README.md`](../README.md) и `LICENSE` пакета.

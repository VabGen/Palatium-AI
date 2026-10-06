# Запуск palatium-ai в Docker

Пошаговая инструкция для Windows (Docker Desktop) и Linux/macOS.

Связанные файлы:

| Файл | Роль |
|------|------|
| [`docker-compose.yml`](../docker-compose.yml) | **полный стек**: Postgres + Redis + Neo4j + LiteLLM + MCP + API |
| [`docker-compose.override.yml`](../docker-compose.override.yml) | отключает MCP/API по умолчанию (профили `docker-mcp`, `docker-api`) |
| [`Dockerfile`](../Dockerfile) | multi-stage образ API (`WITH_GRAPHITI=1` опционально) |
| [`.dockerignore`](../.dockerignore) | исключает секреты и лишний контекст |
| [`scripts/docker-entrypoint.sh`](../scripts/docker-entrypoint.sh) | tini → миграции → uvicorn |
| [`deploy/litellm/config.yaml`](../deploy/litellm/config.yaml) | маршрутизация `tier-*` → реальные провайдеры |
| [`deploy/postgres/init/01-create-databases.sql`](../deploy/postgres/init/01-create-databases.sql) | создаёт БД `langfuse` + расширение `vector` |
| [`docs/secrets.md`](secrets.md) | секреты / Vault / CI |
| [`runbook.md`](runbook.md) | операторский runbook: симптомы, фиксы, полный сброс |
| [`../START.md`](../START.md) | **стартовая инструкция** — setup, `$PROFILE`, 3 режима |

---

## 0. Что поднимается

### Полный Compose (Docker-профиль)

```powershell
cd D:\project\palatium-ai
docker compose --profile docker-mcp --profile docker-api up -d --build
```

| Сервис | Порт | Назначение |
|--------|------|------------|
| `postgres` | 5432 | DialogTurn / memory / knowledge (образ `pgvector/pgvector:pg18`) + БД `langfuse` |
| `redis` | 6379 | HITL / cache / LiteLLM cache |
| `neo4j` | 7474 / 7687 | Graphiti (Browser + Bolt) |
| **`litellm`** | **4000** | **LLM Gateway — маршрутизатор `tier-*` → провайдеры** |
| `mcp-edms` | 8080 | MCP stub EDMS (профиль `docker-mcp`) |
| `mcp-analytics` | 8081 | MCP stub Analytics (профиль `docker-mcp`) |
| `api` | 8000 | FastAPI + agents (профиль `docker-api`) |
| `langfuse` | 3000 | Observability (профиль `observability`) |

> **`docker-compose.override.yml`** отключает MCP/API в Docker по умолчанию.
> Без профилей `docker-mcp` / `docker-api` эти сервисы **не поднимаются** —
> это правильно и защищает от конфликта портов с host-профилем (Poetry).

Memory backends внутри API:

| `MEMORY_BACKEND` | Требования |
|------------------|------------|
| `postgres` (default) | сервис `postgres` |
| `mem0` | `MEM0_API_KEY` (SaaS, без локального контейнера) |
| `graphiti` | сервис `neo4j` + образ с `WITH_GRAPHITI=1` |

```
┌─ docker compose network ──────────────────────────────────────┐
│  postgres   redis   neo4j   litellm:4000                      │
│  mcp-edms:8080   mcp-analytics:8081   api:8000                │
│         ▲                ▲               │                    │
│         └────────────────┴───────────────┤                    │
│              MCP_SERVERS (service DNS)   │                    │
│                                          ▼                    │
│                              PALATIUM_GATEWAY_URL             │
│                              → http://litellm:4000            │
└───────────────────────────────────────────────────────────────┘
```

> Внутри контейнера `localhost` — сам контейнер.
> Compose DNS: `postgres`, `redis`, `neo4j`, `litellm`, `mcp-edms`.

### Только образ API

В образе **только API**. Postgres/Redis/Neo4j/LiteLLM тогда на хосте или в Compose отдельно.

---

## 0.5. Три режима работы

Проект поддерживает **три** режима, которые **нельзя смешивать** (конфликт по портам 8080/8081/8000):

| Режим | Где MCP | Где API | Gateway | Когда использовать |
|---|---|---|---|---|
| **Host** | Poetry (host) | Poetry (host) | — | Ежедневная разработка (hot-reload) |
| **Docker** | Docker | Docker | — | CI / демо / prod-like |
| **Gateway** | Poetry (host) | Poetry (host) | :8090/8091 | Тест политик `pin_allowlist` / `pin_filter` |

В этом документе подробно описан **Docker-режим**. Для Host-режима используйте
`.\scripts\dev-up.ps1` (см. [`../START.md`](../START.md) §4).

### Host-профиль — альтернатива Docker-профилю

Если нужен **hot-reload** кода MCP/API:

```powershell
# Docker держит только инфраструктуру
docker compose up -d postgres redis neo4j litellm

# MCP stubs + API идут через Poetry
.\scripts\dev-up.ps1
```

**Что запустится:**
- API :8000 — Poetry (hot-reload при правке `src/`)
- MCP EDMS :8080 — Poetry
- MCP Analytics :8081 — Poetry

**Остановка:** `.\scripts\dev-down.ps1 -Force` — только host-процессы; занятые Docker-ом
8080/8081 скрипт не тронет (детали: [`START.md`](../START.md) §7).

---

## 1. Предварительные требования

### 1.1. Установить и запустить Docker Desktop

1. Установите [Docker Desktop](https://www.docker.com/products/docker-desktop/).
2. Запустите Docker Desktop и дождитесь статуса **Running**.
3. Проверьте в PowerShell:

```powershell
docker version
docker compose version
```

Оба команды должны ответить без ошибок.

### 1.2. Подготовить окружение приложения

```powershell
cd D:\project\palatium-ai

# если ещё нет:
Copy-Item env\.env.example env\.env
notepad env\.env
```

**Минимум, что нужно заполнить в `env/.env`:**

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

# --- Провайдер (по умолчанию corporate Qwen) ---
QWEN_API_KEY="corporate-llm"
QWEN_BASE_URL="http://model-generative.shared.du.iba/v1"
QWEN_DEFAULT_MODEL="generative-model"
```

> **`POSTGRES_DB=postgres` — это правильно.** Alembic создаёт **схемы** внутри
> (`palatium_ai`, `edms_assistant`, `knowledge`, `memory`), а не отдельную БД.
> Отдельная БД нужна только для Langfuse (`langfuse`).

Для повседневной разработки обычно используют `env/.env` или `env/.env.dev`.

### 1.3. Проверить структуру deploy-файлов

```powershell
Test-Path deploy/litellm/config.yaml                   # маршрутизация tier-*
Test-Path deploy/postgres/init/01-create-databases.sql # init-скрипт langfuse
```

**Если `deploy/postgres/init/01-create-databases.sql` нет — создайте:**

```sql
-- deploy/postgres/init/01-create-databases.sql
-- Runs ONLY on first init of an empty data directory.
-- Docker mounts this into /docker-entrypoint-initdb.d/.

-- Langfuse: отдельная БД, свои таблицы создаёт сам Langfuse.
CREATE DATABASE langfuse;

-- Основная БД приложения: POSTGRES_DB=postgres.
-- Все схемы (palatium_ai, edms_assistant, knowledge, memory) — внутри.
\connect postgres
CREATE EXTENSION IF NOT EXISTS vector;

-- Langfuse тоже хочет vector (не обязательно, но безвредно).
\connect langfuse
CREATE EXTENSION IF NOT EXISTS vector;
```

### 1.4. Поднять зависимости на хосте

**PostgreSQL** и **Redis** должны слушать порты (по умолчанию `5432` / `6379`).

**MCP stubs** в Docker-режиме поднимаются **в Docker** по профилю `docker-mcp`.

Если используете **host-профиль** — stubs поднимите через Poetry:

```powershell
.\scripts\dev-up.ps1
```

---

## 2. Первый запуск (Docker-профиль, полный стек)

### 2.1. Валидация compose и интерполяции

```powershell
# Проверка синтаксиса + подстановки ${VAR}
docker compose --env-file env/.env config --quiet
# Молчит → всё OK. Ошибка → покажет строку.

# Посмотреть, во что развернулись TIER_*
docker compose --env-file env/.env config | Select-String "TIER_NANO|TIER_MID"
```

**Ожидаемый вывод:**
```
TIER_NANO_API_BASE: http://model-generative.shared.du.iba/v1
TIER_NANO_API_KEY: corporate-llm
TIER_NANO_MODEL: openai/generative-model
TIER_NANO_TIMEOUT: "60"
```

> Ключевой момент: `${QWEN_API_KEY}` в `docker-compose.yml` **интерполируется** Compose
> из `.env` до старта контейнера. Внутри контейнера `litellm` переменные `TIER_*`
> приходят уже с реальными значениями.

### 2.2. Поднять Postgres первым

```powershell
docker compose --env-file env/.env up -d postgres
```

**Что произойдёт:**
- Postgres инициализирует `PGDATA` (если том пустой)
- Выполнит `deploy/postgres/init/01-create-databases.sql`:
    - `CREATE DATABASE langfuse;`
    - `\connect postgres; CREATE EXTENSION IF NOT EXISTS vector;`
    - `\connect langfuse; CREATE EXTENSION IF NOT EXISTS vector;`

**Проверка баз и расширений:**

```powershell
# Список баз — должны быть postgres, langfuse, template0/1
docker compose exec postgres psql -U postgres -c "\l"

# Расширения в основной БД — должен быть vector
docker compose exec postgres psql -U postgres -d postgres -c "\dx"

# Схемы приложения (после миграций)
docker compose exec postgres psql -U postgres -d postgres -c "\dn"
```

> ⚠️ Если база `langfuse` **не появилась** — значит volume `palatium_pgdata`
> уже существовал, init-скрипт не выполнялся (он работает только на пустом
> `PGDATA`). Смотрите §9.

### 2.3. Поднять весь стек (с профилями)

```powershell
docker compose --env-file env/.env `
  --profile docker-mcp `
  --profile docker-api `
  up -d --build
```

**Порядок старта** (за счёт `depends_on: condition: service_healthy`):
```
postgres → redis → neo4j → litellm → mcp-edms → mcp-analytics → api
```

**Проверить статусы — все должны быть `healthy`:**

```powershell
docker compose --env-file env/.env ps
```

### 2.4. Альтернатива — Host-профиль (hot-reload)

Если правите код MCP/API и хотите мгновенный reload — используйте host-профиль:

```powershell
# 1. Docker только для инфраструктуры
docker compose --env-file env/.env up -d postgres redis neo4j litellm

# 2. MCP stubs + API через Poetry
.\scripts\dev-up.ps1

# 3. Проверка
.\scripts\dev-status.ps1
```

---

## 3. Проверка LiteLLM Gateway

### 3.1. Health + список моделей

```powershell
curl http://localhost:4000/health/liveliness
# Ожидаем: "I'm alive!"

curl.exe -H "Authorization: Bearer sk-palatium-master" http://localhost:4000/v1/models
# Ожидаем: 5 tier'ов
```

### 3.2. Проверка env внутри контейнера

```powershell
docker compose exec litellm env | Select-String "TIER_NANO"
```

**Ожидаем:**
```
TIER_NANO_API_KEY=corporate-llm
TIER_NANO_API_BASE=http://model-generative.shared.du.iba/v1
TIER_NANO_MODEL=openai/generative-model
TIER_NANO_TIMEOUT=60
```

❌ Если видите `${QWEN_API_KEY}` — интерполяция не сработала. Проверьте, что
в `docker-compose.yml` → `litellm.environment` строки `TIER_*_API_KEY: ${QWEN_API_KEY}`
(а не хардкод).

### 3.3. Тестовый запрос через `tier-mid`

> **PowerShell:** `Invoke-RestMethod` падает с `Response ended prematurely`
> на chunked-ответах LiteLLM. Используйте `curl.exe` (не алиас `curl`),
> и JSON — через переменную, иначе PowerShell ломает кавычки.

```powershell
$json = '{"model":"tier-mid","messages":[{"role":"user","content":"Say OK"}]}'

curl.exe -s -S http://127.0.0.1:4000/v1/chat/completions `
  -H "Authorization: Bearer sk-palatium-master" `
  -H "Content-Type: application/json" `
  --max-time 300 `
  -d $json
```

**Ожидаем:** JSON-ответ. В поле `model` увидите **реальную** модель
(`generative-model`), хотя запрашивали `tier-mid`.

### 3.4. LiteLLM Admin UI (опционально)

Откройте `http://localhost:4000/ui`. Логин: `admin`, пароль: `${LITELLM_MASTER_KEY}`.

---

## 4. Проверка API и остальных сервисов

```powershell
curl http://127.0.0.1:8000/health
# Ожидаем: {"status":"ok"}

curl http://127.0.0.1:8080/health    # MCP EDMS
curl http://127.0.0.1:8081/health    # MCP Analytics

# Swagger UI: http://127.0.0.1:8000/docs
# Neo4j:      http://127.0.0.1:7474   (neo4j / palatium-neo4j)
```

**Логи:**

```powershell
docker compose --env-file env/.env logs -f
docker compose --env-file env/.env logs -f litellm
docker compose --env-file env/.env logs -f api
docker compose logs --tail 100 litellm | Select-String "ERROR|Traceback"
```

При `LOG_LEVEL=DEBUG` видны `agent.node.start` / `agent.node.end`.

---

## 5. Смена модели для tier'а (без правки кода)

Всё в `docker-compose.yml` → сервис `litellm` → `environment`.

Пример — `tier-mid` с Qwen на OpenAI:

```yaml
TIER_MID_MODEL: "openai/gpt-4o"
TIER_MID_API_KEY: ${OPENAI_API_KEY}
TIER_MID_API_BASE: ${OPENAI_BASE_URL}
TIER_MID_TIMEOUT: "60"
```

Применить:

```powershell
docker compose --env-file env/.env up -d --force-recreate litellm
docker compose exec litellm env | Select-String "TIER_MID"
```

**API перезапускать не нужно** — оно ходит в Gateway по псевдониму `tier-mid`.

### Сценарии

**A. Всё на corporate Qwen:**
```yaml
TIER_NANO_MODEL: "openai/generative-model"
TIER_NANO_API_KEY: ${QWEN_API_KEY}
TIER_NANO_API_BASE: ${QWEN_BASE_URL}
```

**B. Ollama Cloud для nano/small, Qwen для остальных:**
```yaml
TIER_NANO_MODEL: "openai/gpt-oss:20b-cloud"
TIER_NANO_API_KEY: ${OLLAMA_API_KEY}
TIER_NANO_API_BASE: https://ollama.com/v1
```

**C. OpenAI для nano/small/mid, Anthropic для frontier/deep:**
```yaml
TIER_NANO_MODEL: "openai/gpt-4o-mini"
TIER_NANO_API_KEY: ${OPENAI_API_KEY}
TIER_NANO_API_BASE: ${OPENAI_BASE_URL}

TIER_FRONTIER_MODEL: "anthropic/claude-sonnet-4-5"
TIER_FRONTIER_API_KEY: ${ANTHROPIC_API_KEY}
TIER_FRONTIER_API_BASE: ${ANTHROPIC_BASE_URL}
```

---

## 6. Профили (опциональные сервисы)

### Langfuse (observability)

Профиль `observability` поднимает Langfuse v3 = `clickhouse` + `langfuse-web` +
`langfuse-worker` (+ `minio`/`silo-init` как хранилище трасс).

**Память — главное ограничение.** Заявленные лимиты: core ~6016 MiB (postgres, redis,
neo4j, litellm, api, minio, MCP) и observability ещё ~3328 MiB. Вместе ~9.1 GiB, поэтому
`make up-full` требует VM не меньше ~9.1 GiB: поднимите `memory=12GB` в
`%USERPROFILE%\.wslconfig` и перезапустите Docker Desktop. На дефолтной VM (~7.7 GiB)
сработает VM-wide OOM killer — и первым он снимет самый крупный RSS (postgres уйдёт в
crash-recovery). Именно поэтому профиль не входит в `make up`, а не «для чистоты».
Этот бюджет закреплён тестом `tests/unit/test_container_hardening.py`.

### Ожидание готовности в `make up` / `make up-full` / `make rebuild-app`

Эти цели не просто делают `up -d`: следом они запускают
`python scripts/attachments_probe.py --wait …` и падают с ненулевым кодом, если
S3-хранилище, clamd или API не ответили за отведённое время (420 s для `up`/`up-full`,
120 s для `rebuild-app`). До этого `make up` печатал «FAIL clamav» на исправно
поднятом стеке: clamd грузит базу сигнатур до 5 минут (`start_period`), а проба
выполнялась сразу после `up -d`.

`docker compose up --wait` для этой роли не годится: у стека есть one-shot контейнер
`silo-init` (создаёт бакеты и выходит с кодом 0), и compose считает любой вышедший
контейнер провалом — на нём `--wait` отклонял полностью healthy запуск. Поэтому
готовность определяют сами проверки, и повторно выполняются только те, что ещё не
прошли (в `--wait 0`, т.е. у `make attach-probe`, поведение прежнее — один проход).

Тот же one-shot проверяется отдельной пробой `silo-init`: она требует код выхода 0,
потому что `api` создаёт свой бакет сам и упавший bootstrap иначе выглядел бы здоровым
стеком без бакета `langfuse`. Статус `Exited (0)` (контейнер «не запущен») — ожидаемый
конечный результат; разовые контейнеры `docker compose run silo-init` в вердикт не
берутся.

```powershell
# БД langfuse создаётся init-скриптом Postgres (см. §2.2).
# Если том уже существовал — создайте вручную:
docker compose exec postgres psql -U postgres -c "CREATE DATABASE langfuse;"

# Поднять только observability (поверх уже работающего стека)
make obs-up
# или вручную
docker compose --env-file env/.env --profile observability up -d minio silo-init clickhouse langfuse-web langfuse-worker
# UI: http://localhost:3000

# Остановить (тома Langfuse/ClickHouse сохраняются; minio не трогаем — он общий с вложениями)
make obs-down
```

### MCP Gateways (Docker-версия)

```powershell
docker compose --env-file env/.env --profile mcp-gateway up -d
# mcp-gateway-edms      → http://localhost:8090
# mcp-gateway-analytics → http://localhost:8091
```

**Host-версия gateway** (для тестирования политик без Docker):
```powershell
.\scripts\dev-up.ps1 -WithGateway
```

### Observability stack (Prometheus / Grafana / Loki / Alertmanager)

```powershell
docker compose --env-file env/.env `
  -f docker-compose.yml `
  -f deploy/observability/compose.observability.yml up -d
```

Детали и SLO — [`../deploy/observability/README.md`](../deploy/observability/README.md)
и [`../deploy/observability/SLO.md`](../deploy/observability/SLO.md).

---

## 7. Запуск через `docker run` (только API, зависимости на хосте)

### 7.1. Базовый запуск

```powershell
cd D:\project\palatium-ai

docker run --rm -p 8000:8000 `
  --name palatium-api `
  --env-file env/.env `
  -e POSTGRES_HOST=host.docker.internal `
  -e REDIS_HOST=host.docker.internal `
  -e PALATIUM_GATEWAY_URL=http://host.docker.internal:4000 `
  -e APP_HOST=0.0.0.0 `
  palatium-ai:local
```

**Ключевое:** если LiteLLM на хосте, из контейнера к нему — `host.docker.internal:4000`,
а не `litellm:4000`.

### 7.2. С миграциями Alembic

```powershell
docker run --rm -p 8000:8000 `
  --env-file env/.env `
  -e POSTGRES_HOST=host.docker.internal `
  -e REDIS_HOST=host.docker.internal `
  -e PALATIUM_GATEWAY_URL=http://host.docker.internal:4000 `
  -e APP_HOST=0.0.0.0 `
  -e RUN_MIGRATIONS=1 `
  palatium-ai:local
```

Лог: `[entrypoint] RUN_MIGRATIONS=1 → alembic upgrade head`.

### 7.3. DEBUG-логи

```powershell
docker run --rm -p 8000:8000 `
  --env-file env/.env.dev `
  -e POSTGRES_HOST=host.docker.internal `
  -e REDIS_HOST=host.docker.internal `
  -e PALATIUM_GATEWAY_URL=http://host.docker.internal:4000 `
  -e APP_HOST=0.0.0.0 `
  -e LOG_LEVEL=DEBUG `
  palatium-ai:local
```

### 7.4. Несколько uvicorn workers

```powershell
docker run --rm -p 8000:8000 `
  --env-file env/.env `
  -e POSTGRES_HOST=host.docker.internal `
  -e REDIS_HOST=host.docker.internal `
  -e PALATIUM_GATEWAY_URL=http://host.docker.internal:4000 `
  -e APP_HOST=0.0.0.0 `
  -e UVICORN_WORKERS=2 `
  palatium-ai:local
```

### 7.5. MCP stubs на хосте

**Рекомендуется:** Host-профиль (`dev-up.ps1`) — см. §2.4.

Если API в Docker, а stubs на хосте:

```powershell
docker run --rm -p 8000:8000 `
  --env-file env/.env `
  -e POSTGRES_HOST=host.docker.internal `
  -e REDIS_HOST=host.docker.internal `
  -e PALATIUM_GATEWAY_URL=http://host.docker.internal:4000 `
  -e APP_HOST=0.0.0.0 `
  -e 'MCP_SERVERS={"edms":"http://host.docker.internal:8080","analytics":"http://host.docker.internal:8081"}' `
  palatium-ai:local
```

---

## 8. Сборка образа API

```powershell
cd D:\project\palatium-ai
docker build -t palatium-ai:local .
```

### Targets

| Команда | Назначение |
|---------|------------|
| `docker build -t palatium-ai:local .` | **runtime** (default) — prod API |
| `docker build --target test -t palatium-ai:test .` | образ с pytest |
| `docker build --target devtools -t palatium-ai:devtools .` | shell + Poetry (не для prod) |

Проверка: `docker images palatium-ai`.

---

## 9. Частые проблемы и решения

### ❌ База `langfuse` не создалась

**Причина:** volume `palatium_pgdata` уже существовал, init-скрипт не выполнился.

**Решение A — пересоздать том (dev):**
```powershell
docker compose --env-file env/.env down -v
docker compose --env-file env/.env up -d postgres
```

**Решение B — создать вручную (prod, данные важны):**
```powershell
docker compose exec postgres psql -U postgres -c "CREATE DATABASE langfuse;"
docker compose exec postgres psql -U postgres -d langfuse -c "CREATE EXTENSION IF NOT EXISTS vector;"
```

### ❌ `palatium_dev does not exist`

**Это нормально.** У вас `POSTGRES_DB=postgres` — все схемы приложения живут
в `postgres`. `palatium_dev` не используется.

Правильные команды:
```powershell
docker compose exec postgres psql -U postgres -d postgres -c "\dn"
docker compose exec postgres psql -U postgres -d postgres -c "\dx"
```

### ❌ LiteLLM падает с `MissingEnvVarError`

**Проверка:**
```powershell
docker compose exec litellm env | Select-String "TIER_"
docker compose --env-file env/.env config | Select-String "TIER_"
```

**Фикс:** в `docker-compose.yml` → `litellm.environment` должны быть
`TIER_*_API_KEY: ${QWEN_API_KEY}`.

### ❌ API не стартует, `depends_on: litellm: service_healthy`

```powershell
docker compose ps litellm
docker compose logs litellm | Select-String "ERROR"
curl http://localhost:4000/health/liveliness
```

### ❌ `Response ended prematurely` при `Invoke-RestMethod`

PowerShell плохо работает с chunked-ответами. Используйте `curl.exe` (§3.3).

### ❌ `Invalid JSON payload: unexpected character`

PowerShell передаёт `\"` буквально. Используйте JSON в переменной через
**одинарные** кавычки (§3.3).

### ❌ Конфликт портов 8080/8081

**Причина:** host MCP (Poetry) и Docker MCP одновременно.
**Фикс:** используйте один режим — см. §0.5.

### ❌ Изменения в `.env` не подхватываются

`docker compose restart` не перечитывает env:
```powershell
docker compose --env-file env/.env up -d --force-recreate <service>
```

### ❌ Порт уже занят

```bash
POSTGRES_PUBLISH_PORT=5433
REDIS_PUBLISH_PORT=6380
API_PUBLISH_PORT=8001
LITELLM_PUBLISH_PORT=4001
```

```powershell
docker compose --env-file env/.env up -d --force-recreate
```

### ❌ Миграции Alembic

```powershell
# Внутри контейнера API
docker compose exec api alembic upgrade head

# На хосте
poetry run alembic upgrade head
```

### Прочие проблемы

| Симптом | Причина | Что сделать |
|---------|---------|-------------|
| `Failed to fetch` в Swagger | API не запущен | `docker compose ps`, `logs api` |
| `connection refused` к Postgres/Redis | `HOST=localhost` внутри контейнера | `POSTGRES_HOST=host.docker.internal` |
| Compose: `POSTGRES_PASSWORD is not set` | нет `--env-file` / нет ключа | `$env:COMPOSE_ENV_FILES="env/.env"` + `. $PROFILE` |
| MCP tools пустые | stubs не в сети с API | Docker-профиль: сервис `mcp-edms`; Host-профиль: `dev-up.ps1` |
| `OSError: Read-only file system: '/.cursor'` | audit писал в `/.cursor/logs` | путь `/app/logs/audit-chain.log` (`AUDIT_LOG_FILE`) |
| `The option "--no-update" does not exist` | Poetry 2.x | в Dockerfile `poetry lock` без `--no-update` |
| `pyproject.toml changed significantly... poetry.lock` | content-hash | убрать `License ::` classifier, `poetry lock` |
| Permission / read-only | Compose `read_only: true` | tmpfs на `/app/tmp`, `/app/logs` |

---

## 10. Остановка и очистка

```powershell
# Остановить Docker-стек
docker compose --env-file env/.env down

# Остановить + удалить volumes (dev reset)
docker compose --env-file env/.env down -v

# Удалить образ
docker rmi palatium-ai:local

# Prune висячих слоёв
docker builder prune -f
```

Host-профиль:
```powershell
.\scripts\dev-down.ps1 -Force
```

---

## 11. Linux / macOS

Те же шаги; вместо PowerShell — bash.
На Linux `host.docker.internal` может отсутствовать — добавьте:

```bash
docker run --rm -p 8000:8000 \
  --add-host=host.docker.internal:host-gateway \
  --env-file env/.env \
  -e POSTGRES_HOST=host.docker.internal \
  -e REDIS_HOST=host.docker.internal \
  -e PALATIUM_GATEWAY_URL=http://host.docker.internal:4000 \
  -e APP_HOST=0.0.0.0 \
  palatium-ai:local
```

---

## 12. Архитектура образа

```
deps (Poetry + lock) → builder (пакет + alembic) → runtime (default)
                                              ↘ test
                                              ↘ devtools
```

- **runtime** — без Poetry/gcc: меньше CVE и размер.
- Entrypoint: `tini` → optional `alembic upgrade head` → `uvicorn`.
- Секреты в образ **не копируются** (см. `.dockerignore`).

Подробнее: [`secrets.md`](secrets.md).

---

## 13. Шпаргалка команд

| Задача | Команда |
|---|---|
| Валидация compose | `docker compose --env-file env/.env config --quiet` |
| Статус всех | `docker compose --env-file env/.env ps` |
| Логи всех | `docker compose --env-file env/.env logs -f` |
| Логи litellm | `docker compose logs -f litellm` |
| Пересоздать сервис | `docker compose --env-file env/.env up -d --force-recreate litellm` |
| Список БД | `docker compose exec postgres psql -U postgres -c "\l"` |
| Схемы | `docker compose exec postgres psql -U postgres -d postgres -c "\dn"` |
| Расширения | `docker compose exec postgres psql -U postgres -d postgres -c "\dx"` |
| SQL-консоль | `docker compose exec postgres psql -U postgres -d postgres` |
| Shell в контейнере | `docker compose exec api sh` |
| Env контейнера | `docker compose exec litellm env \| Select-String "TIER_"` |
| Health LiteLLM | `curl http://localhost:4000/health/liveliness` |
| Модели LiteLLM | `curl.exe -H "Authorization: Bearer sk-palatium-master" http://localhost:4000/v1/models` |
| Health API | `curl http://localhost:8000/health` |
| Миграции | `docker compose exec api alembic upgrade head` |
| Полный reset | `docker compose --env-file env/.env down -v` |

---

## 14. Чеклист «первый успешный запуск»

1. [ ] Docker Desktop **Running**
2. [ ] `env/.env` заполнен (`POSTGRES_PASSWORD`, `LITELLM_MASTER_KEY`, `QWEN_*`)
3. [ ] `docker compose --env-file env/.env config --quiet` — валидно
4. [ ] `docker compose --env-file env/.env config | Select-String "TIER_"` — реальные значения
5. [ ] `docker compose --env-file env/.env up -d postgres` — Postgres healthy
6. [ ] `docker compose exec postgres psql -U postgres -c "\l"` — есть `postgres` и `langfuse`
7. [ ] `docker compose --env-file env/.env --profile docker-mcp --profile docker-api up -d --build` — весь стек healthy
8. [ ] `curl http://127.0.0.1:8000/health` → `ok`
9. [ ] `curl http://localhost:4000/health/liveliness` → `"I'm alive!"`
10. [ ] `curl.exe ...` → 5 tier'ов
11. [ ] Тестовый POST через `tier-mid` (**`curl.exe`**) → ответ от провайдера
12. [ ] Swagger `/docs` открывается
13. [ ] MCP stubs: `:8080/health`, `:8081/health`
14. [ ] (опц.) Neo4j Browser `:7474`
15. [ ] (опц.) Langfuse `:3000` с профилем `observability`
16. [ ] (опц.) LiteLLM UI `:4000/ui`

---

## 15. Порядок для «чистого» первого запуска

```powershell
# 1. Подготовка
Copy-Item env\.env.example env\.env
notepad env\.env     # POSTGRES_PASSWORD, LITELLM_MASTER_KEY, QWEN_*

# 2. Валидация
docker compose --env-file env/.env config --quiet

# 3. Postgres первым
docker compose --env-file env/.env up -d postgres
docker compose exec postgres psql -U postgres -c "\l"                    # postgres, langfuse
docker compose exec postgres psql -U postgres -d postgres -c "\dx"       # vector

# 4. Весь стек (Docker-профиль)
docker compose --env-file env/.env --profile docker-mcp --profile docker-api up -d --build
docker compose --env-file env/.env ps                                    # все healthy

# 5. LiteLLM
curl http://localhost:4000/health/liveliness
curl.exe -H "Authorization: Bearer sk-palatium-master" http://localhost:4000/v1/models
docker compose exec litellm env | Select-String "TIER_NANO"

# 6. API
curl http://localhost:8000/health

# 7. Тест tier-mid
$json = '{"model":"tier-mid","messages":[{"role":"user","content":"Say OK"}]}'
curl.exe -s -S http://127.0.0.1:4000/v1/chat/completions `
  -H "Authorization: Bearer sk-palatium-master" `
  -H "Content-Type: application/json" `
  --max-time 300 `
  -d $json
```

Если все 7 шагов прошли — стек готов.

---

## См. также

- [`../START.md`](../START.md) — **стартовая инструкция** (setup + `$PROFILE` + 3 режима)
- [`handbook.md`](handbook.md) — полный путь от clone до ops
- [`runbook.md`](runbook.md) — операторский runbook: диагностика по симптому, фиксы, полный сброс
- [`secrets.md`](secrets.md) — секреты / Vault / CI
- [`ops-readiness.md`](ops-readiness.md) — чеклист staging/prod

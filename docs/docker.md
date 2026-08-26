# Запуск palatium-ai в Docker

Пошаговая инструкция для Windows (Docker Desktop) и Linux/macOS.

Связанные файлы:

| Файл | Роль |
|------|------|
| [`docker-compose.yml`](../docker-compose.yml) | **полный стек**: Postgres + Redis + Neo4j + MCP + API |
| [`Dockerfile`](../Dockerfile) | multi-stage образ API (`WITH_GRAPHITI=1` опционально) |
| [`.dockerignore`](../.dockerignore) | исключает секреты и лишний контекст |
| [`scripts/docker-entrypoint.sh`](../scripts/docker-entrypoint.sh) | tini → миграции → uvicorn |
| [`deploy/compose.secrets.example.yml`](../deploy/compose.secrets.example.yml) | alias → root compose |
| [`docs/secrets.md`](secrets.md) | секреты / Vault / CI |

---

## 0. Что поднимается

### Полный Compose (рекомендуется)

```powershell
cd D:\project\palatium-ai
docker compose --env-file env/.env up --build
```

| Сервис | Порт | Назначение |
|--------|------|------------|
| `postgres` | 5432 | DialogTurn / memory_items / LangGraph checkpointer |
| `redis` | 6379 | HITL / cache |
| `neo4j` | 7474 / 7687 | Graphiti (Browser + Bolt) |
| `mcp-edms` | 8080 | MCP stub EDMS |
| `mcp-analytics` | 8081 | MCP stub Analytics |
| `api` | 8000 | FastAPI + agents |

Memory backends внутри API:

| `MEMORY_BACKEND` | Требования |
|------------------|------------|
| `postgres` (default) | сервис `postgres` |
| `mem0` | `MEM0_API_KEY` (SaaS, без локального контейнера) |
| `graphiti` | сервис `neo4j` + образ с `WITH_GRAPHITI=1` |

```
┌─ docker compose network ─────────────────────────────────────┐
│  postgres   redis   neo4j                                    │
│  mcp-edms:8080   mcp-analytics:8081   api:8000               │
│         ▲                ▲               │                   │
│         └────────────────┴───────────────┘                   │
│              MCP_SERVERS (service DNS)                       │
└──────────────────────────────────────────────────────────────┘
```

> Внутри контейнера `localhost` — сам контейнер.  
> Compose DNS: `postgres`, `redis`, `neo4j`, `mcp-edms`.

### Только образ API

В образе **только API**. Postgres/Redis/Neo4j тогда на хосте или в Compose отдельно.

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

1. Перейдите в корень репозитория:

```powershell
cd D:\project\palatium-ai
```

2. Убедитесь, что есть рабочий env (секреты **не** попадают в образ):

```powershell
# если ещё нет:
Copy-Item env\.env.example env\.env
# заполните POSTGRES_*, OLLAMA_API_KEY / ключи провайдера
```

Для повседневной разработки обычно используют `env/.env` или `env/.env.dev`.

### 1.3. Поднять зависимости на хосте

**PostgreSQL** и **Redis** должны слушать порты (по умолчанию `5432` / `6379`).

**MCP stubs** при полном Compose (`docker-compose.yml`) поднимаются **в Docker вместе с API** — отдельно `dev-up.ps1` не нужен.

Если запускаете **только** образ API (`docker run palatium-ai:local`), stubs поднимите сами:

```powershell
.\scripts\dev-up.ps1
# и укажите MCP_SERVERS=...host.docker.internal...
```

Либо соберите stubs отдельно:

```powershell
docker build -f mcp_servers/Dockerfile `
  --build-arg MCP_NAME=edms --build-arg MCP_MODULE=edms_mcp_server --build-arg MCP_PORT=8080 `
  -t palatium-mcp-edms:local mcp_servers
```

---

## 2. Сборка образа

Из корня репозитория:

```powershell
cd D:\project\palatium-ai

docker build -t palatium-ai:local .
```

Первая сборка дольше (Poetry + зависимости). Последующие быстрее за счёт BuildKit cache.

### Targets (необязательно)

| Команда | Назначение |
|---------|------------|
| `docker build -t palatium-ai:local .` | **runtime** (default) — prod API |
| `docker build --target test -t palatium-ai:test .` | образ с pytest |
| `docker build --target devtools -t palatium-ai:devtools .` | shell + Poetry (не для prod) |

Проверка, что образ есть:

```powershell
docker images palatium-ai
```

---

## 3. Запуск через `docker run` (рекомендуется для первого раза)

### 3.1. Базовый запуск (API + ваш `env/.env`)

```powershell
cd D:\project\palatium-ai

docker run --rm -p 8000:8000 `
  --name palatium-api `
  --env-file env/.env `
  -e POSTGRES_HOST=host.docker.internal `
  -e REDIS_HOST=host.docker.internal `
  -e APP_HOST=0.0.0.0 `
  palatium-ai:local
```

Что делают флаги:

| Флаг | Смысл |
|------|--------|
| `--rm` | удалить контейнер после остановки |
| `-p 8000:8000` | проброс порта на хост |
| `--env-file env/.env` | все переменные из файла |
| `-e POSTGRES_HOST=...` | переопределить host БД (хост-машина) |
| `-e REDIS_HOST=...` | то же для Redis |
| `-e APP_HOST=0.0.0.0` | слушать все интерфейсы в контейнере |

### 3.2. С миграциями Alembic при старте

```powershell
docker run --rm -p 8000:8000 `
  --name palatium-api `
  --env-file env/.env `
  -e POSTGRES_HOST=host.docker.internal `
  -e REDIS_HOST=host.docker.internal `
  -e APP_HOST=0.0.0.0 `
  -e RUN_MIGRATIONS=1 `
  palatium-ai:local
```

В логе должно появиться: `[entrypoint] RUN_MIGRATIONS=1 → alembic upgrade head`.

### 3.3. DEBUG-логи агентов

```powershell
docker run --rm -p 8000:8000 `
  --env-file env/.env.dev `
  -e POSTGRES_HOST=host.docker.internal `
  -e REDIS_HOST=host.docker.internal `
  -e APP_HOST=0.0.0.0 `
  -e LOG_LEVEL=DEBUG `
  palatium-ai:local
```

### 3.4. Несколько worker-процессов uvicorn

```powershell
docker run --rm -p 8000:8000 `
  --env-file env/.env `
  -e POSTGRES_HOST=host.docker.internal `
  -e REDIS_HOST=host.docker.internal `
  -e APP_HOST=0.0.0.0 `
  -e UVICORN_WORKERS=2 `
  palatium-ai:local
```

### 3.5. MCP stubs

**Рекомендуется:** полный Compose (API + MCP в одной сети) — раздел 4.  
Тогда `dev-up.ps1` не нужен, `MCP_SERVERS` указывает на `http://mcp-edms:8080` и `http://mcp-analytics:8081`.

Если stubs на хосте (`dev-up.ps1`), из контейнера API:

```powershell
docker run --rm -p 8000:8000 `
  --env-file env/.env `
  -e POSTGRES_HOST=host.docker.internal `
  -e REDIS_HOST=host.docker.internal `
  -e APP_HOST=0.0.0.0 `
  -e 'MCP_SERVERS={"edms":"http://host.docker.internal:8080","analytics":"http://host.docker.internal:8081"}' `
  palatium-ai:local
```

---

## 4. Запуск через Docker Compose

### 4.1. Полный стек (рекомендуется)

Из корня репозитория:

```powershell
cd D:\project\palatium-ai

docker compose --env-file env/.env up --build
```

В `env/.env` нужны как минимум:

```env
POSTGRES_PASSWORD="your_password"
OLLAMA_API_KEY="your_key_here"   # или другой LLM-ключ
```

Compose сам поднимет Postgres / Redis / Neo4j / MCP / API и проставит DNS-имена (`POSTGRES_HOST=postgres` и т.д.).

Graphiti SDK в образе (опционально):

```powershell
$env:WITH_GRAPHITI = "1"
$env:MEMORY_BACKEND = "graphiti"
docker compose --env-file env/.env up --build
```

Mem0 (SaaS):

```env
MEMORY_BACKEND=mem0
MEM0_API_KEY=...
```

Фон:

```powershell
docker compose --env-file env/.env up --build -d
```

Логи / стоп:

```powershell
docker compose --env-file env/.env logs -f api
docker compose --env-file env/.env down
```

`deploy/compose.secrets.example.yml` — тонкий alias на корневой compose (для старых скриптов).

### 4.2. Без `--env-file` (только PowerShell)

```powershell
$env:POSTGRES_PASSWORD = "1234"
$env:OLLAMA_API_KEY = "..."
docker compose up --build
```

### 4.3. Что поднимется

| Сервис | URL |
|--------|-----|
| API / Swagger | http://127.0.0.1:8000/docs |
| EDMS MCP | http://127.0.0.1:8080/docs |
| Analytics MCP | http://127.0.0.1:8081/docs |
| Neo4j Browser | http://127.0.0.1:7474 |
| Postgres | localhost:5432 |
| Redis | localhost:6379 |

### 4.4. Только API-образ + зависимости на хосте

Если Postgres/Redis уже на ПК:

```powershell
docker run --rm -p 8000:8000 `
  --env-file env/.env `
  -e POSTGRES_HOST=host.docker.internal `
  -e REDIS_HOST=host.docker.internal `
  -e APP_HOST=0.0.0.0 `
  palatium-ai:local
```

Если API в контейнере, а stubs когда-то на хосте — см. §3.5.

---

## 5. Проверка, что всё работает

### 5.1. Health

```powershell
curl http://127.0.0.1:8000/health
```

Ожидается: `{"status":"ok"}`.

### 5.2. Swagger UI

Откройте в браузере: http://127.0.0.1:8000/docs

Попробуйте `GET /api/agents/health` и `POST /api/intents/process`.

### 5.3. Логи контейнера

```powershell
docker logs -f palatium-api
# или для compose:
docker compose --env-file env/.env logs -f api
```

При `LOG_LEVEL=DEBUG` видны `agent.node.start` / `agent.node.end`.

---

## 6. Остановка и очистка

```powershell
# остановить контейнер по имени
docker stop palatium-api

# список
docker ps -a --filter name=palatium

# удалить образ (по желанию)
docker rmi palatium-ai:local

# prune висячих слоёв сборки
docker builder prune -f
```

---

## 7. Linux / macOS (кратко)

Те же шаги; вместо PowerShell — bash.  
На Linux `host.docker.internal` может отсутствовать — добавьте:

```bash
docker run --rm -p 8000:8000 \
  --add-host=host.docker.internal:host-gateway \
  --env-file env/.env \
  -e POSTGRES_HOST=host.docker.internal \
  -e REDIS_HOST=host.docker.internal \
  -e APP_HOST=0.0.0.0 \
  palatium-ai:local
```

---

## 8. Архитектура образа (кратко)

```
deps (Poetry + lock) → builder (пакет + alembic) → runtime (default)
                                              ↘ test
                                              ↘ devtools
```

- **runtime** — без Poetry/gcc: меньше CVE и размер.
- Entrypoint: `tini` → optional `alembic upgrade head` → `uvicorn`.
- Секреты в образ **не копируются** (см. `.dockerignore`).

Подробнее про секреты: [`docs/secrets.md`](secrets.md).

---

## 9. Типичные проблемы

| Симптом | Причина | Что сделать |
|---------|---------|-------------|
| `Failed to fetch` в Swagger | контейнер/API не запущен | `docker ps`, смотрите `logs` |
| `connection refused` к Postgres/Redis | `HOST=localhost` внутри контейнера | `POSTGRES_HOST=host.docker.internal` (и Redis) |
| Compose: `POSTGRES_PASSWORD is not set` | нет `--env-file` / нет ключа в файле | `docker compose --env-file env/.env ...` |
| MCP tools пустые / ошибки | stubs не в сети с API | Compose: сервис `mcp-edms`; или `dev-up` + `host.docker.internal` |
| `OSError: Read-only file system: '/.cursor'` после process | audit писал в `/.cursor/logs` | путь `/app/logs/audit-chain.log` (`AUDIT_LOG_FILE`); пересоберите `api` |
| `The option "--no-update" does not exist` | Poetry 2.x | в Dockerfile использовать `poetry lock` без `--no-update` |
| `pyproject.toml changed significantly... poetry.lock` | content-hash / classifiers | Dockerfile делает `poetry lock` перед install; локально: убрать `License ::` classifier, `poetry lock` |
| Permission / read-only | Compose `read_only: true` | tmpfs на `/app/tmp`, `/app/logs` уже в примере |
| Healthcheck unhealthy | API ещё стартует (БД) | увеличьте `start_period`, проверьте Postgres |

---

## 10. Чеклист «первый успешный запуск»

1. [ ] Docker Desktop **Running**
2. [ ] `env/.env` заполнен (`POSTGRES_PASSWORD`, LLM-ключ)
3. [ ] `docker compose --env-file env/.env up --build` успешен
4. [ ] `curl http://127.0.0.1:8000/health` → `ok`
5. [ ] Swagger `/docs` открывается
6. [ ] MCP stubs: `:8080/docs`, `:8081/docs`
7. [ ] (опционально) Neo4j Browser `:7474`, `MEMORY_BACKEND=graphiti` + `WITH_GRAPHITI=1`

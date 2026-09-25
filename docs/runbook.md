# Palatium-AI — Полная операторская инструкция (runbook)

Максимально практичное руководство: запуск, диагностика, фиксы по симптомам,
полный сброс. Все команды — Windows PowerShell, из корня `D:\project\palatium-ai`.

Смежные документы:

| Документ | Роль |
|---|---|
| [`../START.md`](../START.md) | старт: setup, `$PROFILE`, три режима, чек-лист |
| [`docker.md`](docker.md) | пошаговый первый запуск Docker-профиля |
| [`handbook.md`](handbook.md) | полный путь: clone → env → Poetry/Docker → API → ops |
| [`ops-readiness.md`](ops-readiness.md) | чек-лист staging/prod |
| [`secrets.md`](secrets.md) | секреты / Vault / CI |

> **Как пользоваться.** Сбой → найдите симптом в §3 → примените фикс.
> Симптом новый → соберите отчёт из §13.

> **Про `--env-file env/.env`.** В `$PROFILE` (см. [`../START.md`](../START.md) §3)
> задано `$env:COMPOSE_ENV_FILES = "env/.env"`, поэтому флаг избыточен.
> В runbook он указан **явно** — чтобы команды работали в чистом терминале
> без подгруженного профиля.

---

## 0. Ежедневные команды (шпаргалка)

```powershell
# Инфраструктура в Docker (postgres, redis, neo4j, litellm)
docker compose --env-file env/.env up -d postgres redis neo4j litellm

# Host-стек через Poetry (API + MCP stubs)
.\scripts\dev-up.ps1

# Полный Docker-стек (api + mcp в контейнерах)
docker compose --env-file env/.env --profile docker-mcp --profile docker-api up -d

# Статус
.\scripts\dev-status.ps1

# Остановка host
.\scripts\dev-down.ps1 -Force

# Остановка Docker
docker compose --env-file env/.env --profile docker-mcp --profile docker-api down
```

---

## 1. Три режима работы

| Режим | Команда | Когда |
|---|---|---|
| **Host** | `docker compose up -d postgres redis neo4j litellm` + `dev-up.ps1` | Ежедневная разработка (hot-reload) |
| **Docker** | `docker compose --profile docker-mcp --profile docker-api up -d` | CI, демо, prod-like |
| **Gateway** | `.\scripts\dev-up.ps1 -WithGateway` | Тест политик MCP |

**Правило:** не смешивать. Host и Docker MCP конфликтуют на портах 8080/8081/8000.

---

## 2. Быстрая диагностика (одна команда)

```powershell
$profiles = "--profile", "docker-mcp", "--profile", "docker-api"

Write-Host "=== Docker ps ===" -ForegroundColor Cyan
docker compose --env-file env/.env @profiles ps

Write-Host "`n=== Порты ===" -ForegroundColor Cyan
@(8000, 8080, 8081, 8082, 8090, 8091, 4000, 5432, 6379, 7474, 7687) | ForEach-Object {
    $conn = Get-NetTCPConnection -LocalPort $_ -State Listen -ErrorAction SilentlyContinue
    if ($conn) { Write-Host ("  :{0,-5} pid={1}" -f $_, $conn.OwningProcess) -ForegroundColor Green }
    else       { Write-Host ("  :{0,-5} —" -f $_) -ForegroundColor DarkGray }
}

Write-Host "`n=== Health ===" -ForegroundColor Cyan
@(
    @{ N = "API";           U = "http://127.0.0.1:8000/health" },
    @{ N = "LiteLLM";       U = "http://127.0.0.1:4000/health/liveliness" },
    @{ N = "MCP EDMS";      U = "http://127.0.0.1:8080/health" },
    @{ N = "MCP Analytics"; U = "http://127.0.0.1:8081/health" }
) | ForEach-Object {
    try {
        $r = Invoke-WebRequest -Uri $_.U -TimeoutSec 2 -UseBasicParsing
        Write-Host ("  {0,-18} OK {1}" -f $_.N, $r.StatusCode) -ForegroundColor Green
    } catch {
        Write-Host ("  {0,-18} FAIL" -f $_.N) -ForegroundColor Red
    }
}

Write-Host "`n=== Api logs (30) ===" -ForegroundColor Cyan
docker compose --env-file env/.env @profiles logs api --tail 30 2>&1

Write-Host "`n=== mcp-edms logs (30) ===" -ForegroundColor Cyan
docker compose --env-file env/.env @profiles logs mcp-edms --tail 30 2>&1
```

> **Почему `@profiles`.** `api` и `mcp-*` объявлены под профилями
> (`docker-compose.override.yml`), а `api.depends_on` ссылается на `mcp-edms` /
> `mcp-analytics`. Поэтому `docker compose logs api` **без** профилей падает с
> `no such service: mcp-analytics`, а с одним только `--profile docker-api` —
> с `invalid compose project`. Нужны **оба** профиля. См. §3.5 и §3.11.

Готовая обёртка: `.\scripts\dev-status.ps1` (+ alias `palatium-status`).

---

## 3. Типичные проблемы — фиксы по симптому

### 3.1. `api` → `ModuleNotFoundError: No module named 'palatium_ai'`

**Причина:** `pyproject.toml` содержит `{ include = "mcp_servers" }`, но корневой
`Dockerfile` не копирует `mcp_servers/` → `poetry install` падает целиком →
`palatium_ai` не устанавливается.

**Статус: ✅ уже исправлено в репозитории.** `mcp_servers` исключён из пакетов
(`pyproject.toml`, блок `[tool.poetry]`):

```toml
packages = [
    { include = "palatium_ai", from = "src" },
#    { include = "mcp_servers" },
]
```

Проверка (регрессия):

```powershell
Select-String -Path pyproject.toml -Pattern "packages" -Context 0,4

poetry check
poetry install --only main
```

**Если симптом вернулся** (кто-то вернул строку обратно) — убрать `include`
и пересобрать без кэша:

```powershell
docker compose --env-file env/.env --profile docker-mcp --profile docker-api down
docker compose --env-file env/.env --profile docker-mcp --profile docker-api build --no-cache api
docker compose --env-file env/.env --profile docker-mcp --profile docker-api up -d
```

### 3.2. `api` → `Unknown default_provider: gateway`

**Причина:** `_SUPPORTED_PROVIDERS` не содержит `"gateway"` **или** образ старый
(запечён прежний код, кэш слоёв).

**Статус: ✅ код в порядке.** `"gateway"` присутствует в обоих реестрах:

- `src/palatium_ai/core/config/llm/__init__.py` — `frozenset({"openai", "anthropic", "ollama", "qwen", "gateway"})`
- `src/palatium_ai/infrastructure/llm/factory.py` — тот же набор
- `src/palatium_ai/core/config/llm/gateway.py` — класс `GatewayLLMConfig`

Значит, причина — **устаревший образ**. Фикс:

```powershell
# 1. Код на хосте
Select-String -Path src\palatium_ai\core\config\llm\__init__.py -Pattern "_SUPPORTED_PROVIDERS"
Select-String -Path src\palatium_ai\infrastructure\llm\factory.py -Pattern "_SUPPORTED_PROVIDERS"

# 2. Что реально в контейнере (exec работает без профилей)
docker compose --env-file env/.env exec api `
    python -c "from palatium_ai.core.config.llm import _SUPPORTED_PROVIDERS as p; print(sorted(p))"

# 3. Пересборка без кэша (нужны ОБА профиля — см. §3.11)
docker compose --env-file env/.env --profile docker-mcp --profile docker-api build --no-cache api
docker compose --env-file env/.env --profile docker-mcp --profile docker-api up -d
```

### 3.3. `mcp-edms` → `ModuleNotFoundError: No module named 'mcp_servers'`

**Причина:** MCP-сервисы собирались корневым `Dockerfile` вместо
`mcp_servers/Dockerfile`, либо `MCP_MODULE` без префикса `mcp_servers.`.

**Статус: ✅ уже исправлено.** В `docker-compose.yml`:

- `dockerfile: mcp_servers/Dockerfile` — **4** сервиса (edms, analytics, gateway-edms, gateway-analytics)
- `MCP_MODULE: mcp_servers.edms.edms_mcp_server` (и аналогично для остальных)
- `PYTHONPATH=/app/src:/app` — в `mcp_servers/Dockerfile`

Проверка (регрессия):

```powershell
# Должно быть 4 совпадения
Select-String -Path docker-compose.yml -Pattern "dockerfile: mcp_servers/Dockerfile"

# Модули — с префиксом mcp_servers.
Select-String -Path docker-compose.yml -Pattern "MCP_MODULE"
```

**Если симптом вернулся** — правильная секция сборки:

```yaml
build:
  context: .
  dockerfile: mcp_servers/Dockerfile       # ← обязательно
  args:
    MCP_NAME: edms
    MCP_MODULE: mcp_servers.edms.edms_mcp_server   # ← с префиксом
    MCP_PORT: "8080"
```

Пересборка:

```powershell
docker rmi palatium-mcp-edms:local palatium-mcp-analytics:local 2>$null
docker compose --env-file env/.env --profile docker-mcp build --no-cache mcp-edms mcp-analytics
```

Проверка образа (см. §8):

```powershell
docker run --rm palatium-mcp-edms:local python -c "import os; print(sorted(os.listdir('/app')))"
# Ожидаем: ['mcp_servers', 'src', ...]

docker run --rm palatium-mcp-edms:local env | Select-String "PYTHONPATH|MCP_"
# Ожидаем: PYTHONPATH=/app/src:/app, MCP_NAME=edms, MCP_MODULE=mcp_servers.edms.edms_mcp_server
```

### 3.4. `network <hash> not found` при `up -d`

**Причина:** баг Docker Desktop после долгой сборки. Сеть создана, но потеряна
в реестре.

**Фикс:**

```powershell
# 1. Retry (обычно хватает)
docker compose --env-file env/.env --profile docker-mcp --profile docker-api up -d

# 2. Если снова — чистка сетей
docker compose --env-file env/.env --profile docker-mcp --profile docker-api down
docker network rm palatium-ai_default 2>$null
docker network prune -f
docker compose --env-file env/.env --profile docker-mcp --profile docker-api up -d --force-recreate

# 3. Если и это не помогло — restart Docker Desktop
#    (трей → Restart), дождаться "Engine running", повторить шаг 2
```

> Имя сети — `<project>_default`, проект задан в `docker-compose.yml`
> как `name: palatium-ai`.

### 3.5. `no such service: mcp-analytics` при `build api`

**Причина:** сервисы под профилями — Compose не активирует их без явного флага.

**Фикс:** всегда указывать **оба** профиля, если команда касается `api`
(у него в `depends_on` есть MCP — см. §3.11):

```powershell
docker compose --env-file env/.env --profile docker-mcp --profile docker-api build --no-cache api
```

> Один `--profile docker-api` **не** спасёт:
> `service "api" depends on undefined service "mcp-edms": invalid compose project`.

### 3.6. Конфликт портов (host vs Docker)

**Симптом:** `bind: Only one usage of each socket address`.

**Фикс:**

```powershell
# Убить host-процессы
.\scripts\dev-down.ps1 -Force

# Удалить Docker MCP (если поднимали)
docker compose --env-file env/.env --profile docker-mcp rm -f mcp-edms mcp-analytics

# Поднять один режим
docker compose --env-file env/.env up -d postgres redis neo4j litellm
.\scripts\dev-up.ps1
```

### 3.7. Postgres падает / `in recovery mode`

**Симптом:** циклический restart, `database system was not properly shut down`.

**Фикс:** пересоздать volume (данные потеряются):

```powershell
docker compose --env-file env/.env down
docker volume rm palatium-ai_palatium_pgdata
docker compose --env-file env/.env up -d postgres
```

> Имя volume — `<project>_<volume>` = `palatium-ai_palatium_pgdata`
> (том объявлен как `palatium_pgdata`, проект — `palatium-ai`).
> Убедиться можно так: `docker volume ls | Select-String palatium`.

### 3.8. `palatium_dev does not exist`

**Это нормально.** У вас `POSTGRES_DB=postgres`, всё живёт там. Используйте:

```powershell
docker compose exec postgres psql -U postgres -d postgres -c "\dn"
```

### 3.9. `docker compose <command>` не видит `env/.env`

**Симптом:** `POSTGRES_PASSWORD is not set` или значения `TIER_*` пустые.

**Фикс:** глобальная переменная в `$PROFILE`:

```powershell
$env:COMPOSE_ENV_FILES = "env/.env"
. $PROFILE
```

Без профиля — явный флаг `--env-file env/.env` в каждой команде.

### 3.10. `failed to read env/.env: unexpected character`

**Причина:** в `.env` попали команды PowerShell.

**Фикс:**

```powershell
Copy-Item env\.env env\.env.backup
$clean = Get-Content env/.env | Where-Object {
    $_ -match '^\s*#' -or
    $_ -match '^\s*$' -or
    $_ -match '^\s*[A-Za-z_][A-Za-z0-9_]*\s*='
}
$clean | Set-Content env/.env -Encoding utf8NoBOM   # PS 7: BOM не добавляется
```

> В Windows PowerShell 5.1 используйте `-Encoding UTF8` (BOM) — но тогда
> проверьте, что парсер `.env` его переносит. В PowerShell 7 `utf8NoBOM` — канон.

### 3.11. `no such service: mcp-analytics` / `invalid compose project` при `logs`, `ps`, `build`

**Причина:** `api` объявлен под профилем `docker-api`, а его `depends_on` —
сервисы `mcp-edms` / `mcp-analytics` под профилем `docker-mcp`. Compose
разрешает зависимости по модели проекта, поэтому:

- без профилей → `no such service: mcp-analytics`;
- только `--profile docker-api` → `service "api" depends on undefined service "mcp-edms": invalid compose project`.

**Правило: включаешь профили — включай оба** (`docker-mcp` + `docker-api`).

Проверено на Compose v5:

| Команда | Без профилей | Оба профиля |
|---|---|---|
| `docker compose ps` (без имени сервиса) | ✅ показывает всё запущенное | ✅ |
| `docker compose ps api` | ❌ | ✅ |
| `docker compose logs api` | ❌ | ✅ |
| `docker compose logs litellm` / `logs mcp-edms` | ✅ (нет профильных зависимостей) | ✅ |
| `docker compose exec api sh` | ✅ (резолв по запущенному контейнеру) | ✅ |
| `docker compose up -d postgres redis neo4j litellm` | ✅ | ✅ |
| `docker compose build api` | ❌ | ✅ |
| `docker compose config --services` | ✅ только инфра (postgres, redis, neo4j, litellm) | ✅ + `api`, `mcp-edms`, `mcp-analytics` |

Обобщение: **любая команда, принимающая имя сервиса (кроме `exec`), требует
активации профилей сервиса и его зависимостей.**

```powershell
# Плохо (Docker-режим)
docker compose logs api
docker compose --profile docker-api build api        # invalid compose project

# Хорошо
docker compose --env-file env/.env --profile docker-mcp --profile docker-api logs api --tail 50
docker compose --env-file env/.env --profile docker-mcp --profile docker-api build api
docker compose --env-file env/.env --profile docker-mcp --profile docker-api restart api

# exec работает и без профилей — контейнер уже запущен
docker compose --env-file env/.env exec api sh
```

> `docker compose ps` **без имени сервиса** показывает все запущенные контейнеры
> проекта, включая профильные: Compose смотрит на реальные контейнеры, а не на
> активированную модель. Поэтому пустой `ps` — не доказательство, что профили
> не поднимались.

**Альтернатива (host-режим):** миграции и shell — через Poetry, без Docker:

```powershell
poetry run alembic upgrade head
```

### 3.12. `did not find expected '-' indicator` при любой команде `docker compose`

**Симптом:** падает **любая** подкоманда, включая `config --quiet`:

```
go-yaml load error in parser (while parsing a block collection) at L125.C7-L144.C7:
did not find expected '-' indicator
```

**Причина:** в блоке `environment:` смешаны **два стиля** — список
(`- KEY=value`) и маппинг (`KEY: value`). YAML так нельзя: значение ключа
`environment` должно быть либо целиком последовательностью, либо целиком
отображением.

```yaml
# ❌ СЛОМАНО — список + маппинг в одном environment
environment:
  - LITELLM_MASTER_KEY=${LITELLM_MASTER_KEY}
  - LITELLM_LOG=${LITELLM_LOG:-INFO}
  TIER_NANO_MODEL: "openai/generative-model"     # ← '- ' ожидался здесь
  TIER_NANO_API_KEY: ${QWEN_API_KEY}
```

**Фикс — привести к одному стилю.** Вариант A (маппинг, как в остальном файле):

```yaml
environment:
  LITELLM_MASTER_KEY: ${LITELLM_MASTER_KEY}
  LITELLM_LOG: ${LITELLM_LOG:-INFO}
  TIER_NANO_MODEL: "openai/generative-model"
  TIER_NANO_API_KEY: ${QWEN_API_KEY}
```

Вариант B (список — тогда **все** строки блока, включая `TIER_*`):

```yaml
environment:
  - LITELLM_MASTER_KEY=${LITELLM_MASTER_KEY}
  - LITELLM_LOG=${LITELLM_LOG:-INFO}
  - TIER_NANO_MODEL=openai/generative-model
  - TIER_NANO_API_KEY=${QWEN_API_KEY}
```

Поиск смешения:

```powershell
# list-стиль в блоке environment
Select-String -Path docker-compose.yml -Pattern '^\s+- [A-Z][A-Z0-9_]*='

# валидация
docker compose --env-file env/.env config --quiet
```

> Замечание: если сервис уже имеет `env_file: ./env/.env`, то дублирующие
> `LITELLM_*` в `environment` избыточны — `env_file` их и так передаёт.

### 3.13. `api` → `litellm.AuthenticationError` … `token_not_found_in_db` (HTTP 401)

**Симптом (в логах `api`):**

```
Invalid proxy server token passed. Received API Key = sk-..., Key Hash (Token) =<sha256>
... Unable to find token in cache or `LiteLLM_VerificationTokenTable`
litellm.exceptions.AuthenticationError ... 401
```

**Причина:** `PALATIUM_GATEWAY_KEY` содержит плейсхолдер (`sk-palatium-app`), которого
нет в таблице `LiteLLM_VerificationToken`. LiteLLM хеширует присланный токен и ищет его
в БД — не находит → 401 на каждом LLM-вызове (все узлы графа падают).

**Фикс:**

```powershell
# 1. Сгенерировать скоуп-ключ приложения и записать его в env/.env
.\scripts\litellm-provision-key.ps1

# 2. Пересоздать api, чтобы подхватил новый ключ
docker compose --env-file env/.env --profile docker-mcp --profile docker-api up -d api
```

Скрипт идемпотентен: если текущий ключ уже валиден — ничего не меняет; иначе создаёт
новый virtual key (`models` = tier-* из `deploy/litellm/config.yaml`) через
`POST /key/generate`.

> **Защита от повторения:** `docker-compose.yml` и `dev-up.ps1` больше не подставляют
> плейсхолдер. Пустой/незаданный `PALATIUM_GATEWAY_KEY` → подставляется
> `LITELLM_MASTER_KEY` (валиден), т.е. молчаливого 401 из-за заглушки быть не может.

### 3.14. `api` → `Transient error HTTPConnectionPool(host='localhost', port=4317)` / `Failed to export span batch`

**Причина:** `OTEL_ENDPOINT=http://localhost:4317` задан, но OTel-коллектора внутри
`api`-контейнера нет (`localhost` = сам контейнер). Экспортёр ретраит и спамит лог.

**Фикс (отключить трейсинг локально):**

```powershell
# env/.env
OTEL_ENDPOINT=""

docker compose --env-file env/.env --profile docker-mcp --profile docker-api up -d api
```

В логе появится `otel.tracing.disabled reason='OTEL_ENDPOINT unset'`, ретраи прекратятся.
Нужен реальный трейсинг — указать URL коллектора (например `http://otel-collector:4317`,
см. `deploy/observability/`), а не `localhost`.

### 3.15. `api` помечен `unhealthy` при живом `/health`

**Причина:** в healthcheck `api` указан неверный порт (`8080` вместо `8000`).

**Фикс:** в `docker-compose.yml` healthcheck `api` должен дергать
`http://127.0.0.1:8000/health`, затем:

```powershell
docker compose --env-file env/.env --profile docker-mcp --profile docker-api up -d api
docker inspect --format '{{.State.Health.Status}}' palatium-ai-api-1   # → healthy
```

---

## 4. Полная последовательность: чистый запуск Docker-профиля

```powershell
cd D:\project\palatium-ai

# ─── 1. Полный down ───
docker compose --env-file env/.env --profile docker-mcp --profile docker-api down

# ─── 2. Удалить старые MCP-образы (если менялся Dockerfile) ───
docker rmi palatium-mcp-edms:local palatium-mcp-analytics:local 2>$null

# ─── 3. Проверить pyproject.toml ───
Select-String -Path pyproject.toml -Pattern "packages" -Context 0,5
# Должно быть только palatium_ai без mcp_servers

# ─── 4. Проверить docker-compose.yml ───
Select-String -Path docker-compose.yml -Pattern "dockerfile: mcp_servers/Dockerfile"
# Должно быть 4 совпадения (edms, analytics, gateway-edms, gateway-analytics)

# ─── 5. Пересборка без кэша ───
docker compose --env-file env/.env --profile docker-mcp --profile docker-api build --no-cache api mcp-edms mcp-analytics

# ─── 6. Поднять ───
docker compose --env-file env/.env --profile docker-mcp --profile docker-api up -d

# ─── 7. Проверка ───
Start-Sleep 20
docker compose --env-file env/.env --profile docker-mcp --profile docker-api ps

# ─── 8. Health ───
curl.exe http://127.0.0.1:8000/health
curl.exe http://127.0.0.1:4000/health/liveliness
curl.exe http://127.0.0.1:8080/health
curl.exe http://127.0.0.1:8081/health
```

**Ожидаемо:**

```
NAME                          STATUS
palatium-ai-api-1             Up (healthy)
palatium-ai-litellm-1         Up (healthy)
palatium-ai-mcp-analytics-1   Up (healthy)
palatium-ai-mcp-edms-1        Up (healthy)
palatium-ai-neo4j-1           Up (healthy)
palatium-ai-postgres-1        Up (healthy)
palatium-ai-redis-1           Up (healthy)

{"status":"ok"}
"I'm alive!"
{"status":"ok","server":"edms"}
{"status":"ok","server":"analytics"}
```

> Форма ответов `/{health}` зафиксирована в коде:
> `{"status": "ok"}` — `presentation/api/routers/health.py`,
> `{"status": "ok", "server": ...}` — `mcp_servers/mcp_stub_runtime.py` (`mount_health`).

---

## 5. Проверка LiteLLM и tier-маршрутизации

```powershell
# Список tier'ов (ожидаем 5: nano, small, mid, frontier, deep)
curl.exe -H "Authorization: Bearer sk-palatium-master" http://127.0.0.1:4000/v1/models

# Тестовый запрос через tier-mid
$json = '{"model":"tier-mid","messages":[{"role":"user","content":"Say OK"}]}'

curl.exe -s -S http://127.0.0.1:4000/v1/chat/completions `
  -H "Authorization: Bearer sk-palatium-master" `
  -H "Content-Type: application/json" `
  --max-time 300 `
  -d $json

# Проверка env внутри litellm
docker compose exec litellm env | Select-String "TIER_MID"
# Ожидаем: TIER_MID_MODEL=openai/generative-model, TIER_MID_API_KEY=corporate-llm, ...
```

**В ответе** `model` должен быть `generative-model` (реальная), а не `tier-mid` —
это признак, что маршрутизация `deploy/litellm/config.yaml` работает.

### 5.1. Скоуп-ключ приложения (не master)

Приложение ходит в gateway НЕ под `LITELLM_MASTER_KEY`, а под отдельным virtual key:

```powershell
.\scripts\litellm-provision-key.ps1   # идемпотентно, пишет sk-... в env/.env
```

Проверка, что ключ приложения валиден (не 401 — см. §3.13):

```powershell
# уронить и поднять turn агента; в логах api НЕ должно быть AuthenticationError
docker logs palatium-ai-api-1 --since 2m | Select-String "AuthenticationError|agent.turn.start"
```

---

## 6. Проверка БД

```powershell
# Список БД (postgres, langfuse, template0/1)
docker compose exec postgres psql -U postgres -c "\l"

# Схемы в основной БД
docker compose exec postgres psql -U postgres -d postgres -c "\dn"
# Ожидаем: public, palatium_ai, edms_assistant, knowledge, memory

# Расширения
docker compose exec postgres psql -U postgres -d postgres -c "\dx"
# Ожидаем: vector, plpgsql, ...

# Версия Alembic
docker compose exec postgres psql -U postgres -d postgres `
  -c "SELECT version_num FROM palatium_ai.alembic_version;"

# Создать БД langfuse (если init-скрипт не сработал)
docker compose exec postgres psql -U postgres -c "CREATE DATABASE langfuse;"
```

> Init-скрипт `deploy/postgres/init/01-create-databases.sql` выполняется
> **только** при пустом `PGDATA`. Если том уже был — БД `langfuse` создаётся
> вручную (команда выше). См. [`docker.md`](docker.md) §9.

---

## 7. Работа с логами

```powershell
# Все сервисы (Docker)
docker compose --env-file env/.env --profile docker-mcp --profile docker-api logs -f

# Один сервис (профильные сервисы — с --profile, см. §3.11)
docker compose --env-file env/.env --profile docker-api --profile docker-mcp logs -f api
docker compose --env-file env/.env logs -f litellm
docker compose --env-file env/.env --profile docker-mcp logs -f mcp-edms
docker compose --env-file env/.env --profile docker-mcp logs -f mcp-analytics

# Ошибки
docker compose --env-file env/.env --profile docker-mcp --profile docker-api logs --tail 100 api | Select-String "ERROR|Traceback"

# Host-стек (Poetry) — файлы пишет dev-up.ps1
Get-Content scripts\.dev\logs\palatium-ai.stdout.log -Tail 50
Get-Content scripts\.dev\logs\palatium-ai.stderr.log -Tail 50
Get-Content scripts\.dev\logs\mcp-edms.stderr.log -Tail 50
Get-Content scripts\.dev\logs\mcp-analytics.stderr.log -Tail 50
Get-Content scripts\.dev\logs\mcp-gateway-edms.stderr.log -Tail 50
```

> Имена файлов — `scripts/.dev/logs/<service>.{stdout,stderr}.log`
> (см. `scripts/dev-up.ps1`). Готовые обёртки: `palatium-logs-api`,
> `palatium-logs-all`.

---

## 8. Проверка образов (что реально внутри)

```powershell
# API-образ
docker run --rm palatium-ai:local python -c "import os; print(sorted(os.listdir('/app')))"
# Ожидаем: ['alembic', 'alembic.ini', 'src', ...] — БЕЗ mcp_servers

docker run --rm palatium-ai:local python -c "import palatium_ai; print(palatium_ai.__file__)"
# Ожидаем: /app/src/palatium_ai/__init__.py

# MCP-образ
docker run --rm palatium-mcp-edms:local python -c "import os; print(sorted(os.listdir('/app')))"
# Ожидаем: ['mcp_servers', 'src']

docker run --rm palatium-mcp-edms:local env | Select-String "PYTHONPATH|MCP_"
# Ожидаем: PYTHONPATH=/app/src:/app, MCP_NAME=edms, MCP_MODULE=mcp_servers.edms.edms_mcp_server
```

> Корневой `Dockerfile` копирует только `src/`, `alembic/`, `alembic.ini`,
> `scripts/docker-entrypoint.sh` — `mcp_servers/` туда не попадает.
> `mcp_servers/Dockerfile` копирует `mcp_servers/*.py`, нужную подпапку
> `${MCP_NAME}/` и минимальный набор `src/palatium_ai/domain/mcp/*`.

---

## 9. Перезапуск отдельных сервисов

```powershell
# Пересоздать один сервис (после правки deploy/litellm/config.yaml)
docker compose --env-file env/.env up -d --force-recreate litellm

# Перезапустить (без пересоздания)
docker compose --env-file env/.env --profile docker-mcp --profile docker-api restart api

# Пересобрать один сервис
docker compose --env-file env/.env --profile docker-mcp --profile docker-api build api
docker compose --env-file env/.env --profile docker-mcp --profile docker-api up -d api
```

Обёртка: `palatium-build [api|test|devtools]`.

---

## 10. Полный сброс (ядерный вариант)

**Удаляет все volumes → все данные потеряются.**

```powershell
cd D:\project\palatium-ai

# 1. Остановить host
.\scripts\dev-down.ps1 -Force

# 2. Остановить Docker + удалить volumes
docker compose --env-file env/.env --profile docker-mcp --profile docker-api down -v

# 3. Удалить образы проекта
docker rmi palatium-ai:local palatium-mcp-edms:local palatium-mcp-analytics:local `
    palatium-mcp-gateway-edms:local palatium-mcp-gateway-analytics:local 2>$null

# 4. Очистить сети
docker network prune -f

# 5. Очистить build cache
docker builder prune -f

# 6. Поднять инфру
docker compose --env-file env/.env up -d postgres redis neo4j litellm

# 7. Проверить, что БД создались (init-скрипт)
docker compose exec postgres psql -U postgres -c "\l"
# Должны быть: postgres, langfuse

# 8. Пересобрать всё без кэша
docker compose --env-file env/.env --profile docker-mcp --profile docker-api build --no-cache

# 9. Поднять
docker compose --env-file env/.env --profile docker-mcp --profile docker-api up -d

# 10. Ждать 20-30 секунд, проверить
docker compose --env-file env/.env --profile docker-mcp --profile docker-api ps
```

---

## 11. Полезные команды в `$PROFILE`

Базовый набор `palatium-*` описан в [`../START.md`](../START.md) §3.
Команды из этого runbook уже покрыты (набор пополнен обёртками Docker-стека):

| Из §0/§2/§4/§10/§13 | Готовая команда |
|---|---|
| полный Docker-стек (оба профиля) | `palatium-docker-up` / `palatium-docker-down` |
| сборка сервисов | `palatium-docker-build [services] [-NoCache]` |
| build API / test / devtools | `palatium-build api\|test\|devtools` |
| health-чек всех сервисов | `palatium-health` |
| порты | `palatium-ports` |
| `docker compose ps` | `palatium-docker-ps` |
| `docker compose logs -f [svc]` | `palatium-docker-logs [service]` |
| `\|\| docker compose <args>` | `dcompose <args>` |
| отчёт из §13 | `palatium-diag` |
| статус host-стека | `palatium-status` |

Реализация (см. `$PROFILE`, блок «Palatium-AI»):

```powershell
function palatium-docker-up {
    docker compose --profile docker-mcp --profile docker-api up -d @args
}

function palatium-docker-down {
    docker compose --profile docker-mcp --profile docker-api down @args
}

function palatium-docker-build {
    param(
        [string[]]$Service = @("api"),
        [switch]$NoCache
    )
    $extra = @()
    if ($NoCache) { $extra += "--no-cache" }
    docker compose --profile docker-mcp --profile docker-api build @extra @Service
}

function palatium-diag {
    & "$script:PalatiumRoot\scripts\diag-report.ps1" @args
}
```

> Профили зашиты внутрь обёрток — так правило «оба профиля» (§3.11) нельзя
> нарушить по невнимательности. `--env-file` не нужен: в `$PROFILE` задано
> `$env:COMPOSE_ENV_FILES = "env/.env"`.

---

## 12. Чек-лист перед коммитом / PR

Статус — состояние репозитория на момент написания runbook.

```
[x] pyproject.toml: packages = [{ include = "palatium_ai", from = "src" }]
[x] pyproject.toml: [tool.mypy] mypy_path = ["src"], exclude содержит mcp_servers/
[x] docker-compose.yml: для всех mcp-* стоит dockerfile: mcp_servers/Dockerfile
[x] docker-compose.yml: MCP_MODULE = mcp_servers.X.Y_mcp_server
[x] .dockerignore: НЕ содержит mcp_servers/
[x] factory.py: _SUPPORTED_PROVIDERS содержит "gateway"
[x] core/config/llm/__init__.py: _SUPPORTED_PROVIDERS содержит "gateway"
[x] core/config/llm/gateway.py: существует, класс GatewayLLMConfig
[x] src/__init__.py: удалён (не нужен, вызывает конфликт mypy)
[ ] poetry check → All set!
[ ] poetry run mypy . → чисто (или известные проблемы)
[ ] docker compose --env-file env/.env config --quiet → молчит
```

Одной командой:

```powershell
poetry check
poetry run mypy .
docker compose --env-file env/.env config --quiet
Select-String -Path docker-compose.yml -Pattern "dockerfile: mcp_servers/Dockerfile"
Select-String -Path docker-compose.yml -Pattern "MCP_MODULE"
```

---

## 13. Что делать, если ничего не помогло

**Готовый скрипт** (рекомендуется) — соберёт отчёт и вырежет секреты:

```powershell
.\scripts\diag-report.ps1                        # → diag-report.txt в корне
.\scripts\diag-report.ps1 -Tail 200
.\scripts\diag-report.ps1 -EnvFile env/.env.dev -OutFile C:\temp\diag.txt
```

Что собирает: версии Docker/Compose, контейнеры (с профилями и без), сети,
volumes, образы, занятость портов, логи `api` / `mcp-edms` / `mcp-analytics` /
`litellm`, секции `[tool.poetry]` и `dockerfile:`, host-процессы из
`scripts/.dev/processes.json`.

Перед записью вывод прогоняется через redaction: `Bearer …`, `sk-*`,
`PASSWORD=`, `API_KEY=`, `secret`, `token`, PEM-блоки → `<redacted>` (020).

Если скрипт недоступен — тот же отчёт вручную:

```powershell
$profiles = "--profile", "docker-mcp", "--profile", "docker-api"

$report = @"
=== System ===
Docker: $(docker --version)
Compose: $(docker compose version)

=== Containers ===
$(docker compose --env-file env/.env @profiles ps)

=== Networks ===
$(docker network ls)

=== Volumes ===
$(docker volume ls)

=== Images ===
$(docker images | Select-String palatium)

=== Api logs ===
$(docker compose --env-file env/.env @profiles logs api --tail 50 2>&1)

=== mcp-edms logs ===
$(docker compose --env-file env/.env @profiles logs mcp-edms --tail 50 2>&1)

=== mcp-analytics logs ===
$(docker compose --env-file env/.env @profiles logs mcp-analytics --tail 50 2>&1)

=== litellm logs ===
$(docker compose --env-file env/.env logs litellm --tail 30 2>&1)

=== pyproject.toml [tool.poetry] ===
$((Select-String -Path pyproject.toml -Pattern "\[tool.poetry\]" -Context 0,10).Context.PostContext -join "`n")

=== docker-compose.yml MCP sections ===
$((Select-String -Path docker-compose.yml -Pattern "dockerfile:" -Context 2,2 | Out-String))
"@

$report | Out-File -FilePath diag-report.txt -Encoding UTF8
Write-Host "Report saved: diag-report.txt" -ForegroundColor Green
```

**Прикрепите `diag-report.txt`** — по нему точно видно, где рассинхрон.

> Ручной вариант **не** вырезает секреты. `diag-report.txt` добавлен
> в `.gitignore` — коммитить его не нужно.

---

## 14. Итоговая карта портов

| Порт | Сервис | Где |
|---|---|---|
| 8000 | API | host или Docker |
| 8080 | MCP EDMS | host или Docker |
| 8081 | MCP Analytics | host или Docker |
| 8082 | Platform MCP | host (opt-in) |
| 8090 | Gateway EDMS | host (opt-in) |
| 8091 | Gateway Analytics | host (opt-in) |
| 4000 | LiteLLM | Docker |
| 5432 | Postgres | Docker |
| 6379 | Redis | Docker |
| 7474 / 7687 | Neo4j | Docker |
| 3000 | Langfuse | Docker (profile) |

---

## 15. Правила на каждый день

1. **Один режим** — Host **или** Docker. Никогда оба одновременно.
2. **Всегда с профилями** — если команда касается `api`, `mcp-*`, то нужны
   `--profile docker-mcp` / `--profile docker-api` (иначе `no such service`).
3. **`--no-cache` после правки Dockerfile, `pyproject.toml`, requirements**.
4. **`docker rmi` перед `--no-cache build`**, если менялась структура packages.
5. **Логи — первое, куда смотреть.** `docker compose logs <service> --tail 50`.
6. **`poetry check` перед build** — ловит ошибки `pyproject.toml` до Docker.
7. **`docker compose config --quiet`** — валидация compose без запуска.

---

## См. также

- [`../START.md`](../START.md) — старт: setup, `$PROFILE`, три режима
- [`docker.md`](docker.md) — пошаговый запуск Docker-профиля и troubleshooting
- [`handbook.md`](handbook.md) — полный путь от clone до ops
- [`ops-readiness.md`](ops-readiness.md) — чеклист staging/prod
- [`secrets.md`](secrets.md) — секреты / Vault / CI

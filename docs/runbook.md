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

# Всё, кроме observability: API + MCP + вложения (AV/S3) — дефолтный запуск
make up

# Полная сборка и запуск, включая observability (Langfuse v3 + ClickHouse)
#   требует VM ≥ ~9.1 GiB (см. `make up-full` и docs/docker.md)
make up-full

# Пересобрать и перезапустить только api + MCP (инфра не трогается)
make rebuild-app
```

`make up`, `make up-full` и `make rebuild-app` завершаются **только когда стек реально
отвечает**: после `up -d` они запускают `attachments_probe.py --wait` и возвращают
ненулевой код, если за отведённое время S3/clamd/API не поднялись. Ждать приходится на
уровне probe, а не `docker compose up --wait`: one-shot контейнер `silo-init` (создаёт
бакеты и выходит с кодом 0) для compose — «упавший» контейнер, и `--wait` отклонял
исправно поднятый стек. Повторно проверяются только те пробы, что ещё не ответили,
поэтому холодный старт clamd (загрузка сигнатур до ~5 мин) не превращается в серию
лишних запросов к уже зелёному store. `make rebuild-app` печатает и эффективные
бэкенды (`blob_backend=`/`scanner_backend=`) — пересборка без overlay-файлов вложений
молча вернула бы API на dev-бэкенды из `env/.env`.

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
| **Docker** | `docker compose --profile docker-mcp --profile docker-api up -d` | CI, демо, prod-like (без вложений) |
| **Docker + вложения** | `make up` (меню: STACK → *Start stack*) | Дефолтный запуск: AV/S3-путь вложений «из коробки» (§16.8). Обязателен при `ATTACHMENTS_BLOB_BACKEND=minio` — без store API падает на boot |
| **Docker + вложения + observability** | `make up-full` (меню: STACK → *Start full stack*) | Трассировка Langfuse v3; требует VM ≥ ~9.1 GiB (§16.10) |
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

Симптом: контейнер `api` стартует и падает в `docker-entrypoint.sh` на шаге
`RUN_MIGRATIONS=1 → ensure schema + alembic upgrade head`. **Две известные причины** — обе
дают ровно этот трейс, различаются они только логом сборки.

#### 3.1.1. `license-files = ["LICENSE"]`, а `LICENSE` не копируется в образ

**Причина:** `pyproject.toml` объявляет `license-files = ["LICENSE"]`. `poetry install`
ставит корневой проект **последним** — уже после всех сторонних зависимостей. Если
`LICENSE` нет в build-контексте, бэкенд Poetry не может собрать корневой пакет, установка
обрывается, и в venv остаются зависимости без самого `palatium_ai`.

**Почему это было невидимо:** `|| true`, который делал best-effort очистку `__pycache__`,
стоял в конце всей `&&`-цепочки и глушил падение `poetry install`. Образ собирался
«успешно», а падал уже контейнер. Симптом в логе сборки:

```text
Installing the current project: palatium-ai (0.1.0)
No files found for license file glob pattern 'LICENSE'
```

**Статус: ✅ исправлено.** `Dockerfile` копирует `LICENSE`, а очистка вынесена в
отдельный `RUN`; кроме того, сборка теперь **проверяет импорт** на этапе build:

```dockerfile
COPY pyproject.toml poetry.lock README.md LICENSE ./
...
    && /app/.venv/bin/python -c "import palatium_ai; print('palatium_ai ->', palatium_ai.__file__)"
```

Регрессия закреплена тестом `tests/unit/test_dockerfile_build_contract.py` (4 связи:
LICENSE копируется, импорт проверяется, `graphiti` проверяется при `WITH_GRAPHITI=1`,
`|| true` не висит в конце install-цепочки).

#### 3.1.2. `mcp_servers` в `[tool.poetry].packages`

**Причина:** `pyproject.toml` когда-то содержал `{ include = "mcp_servers" }`, но корневой
`Dockerfile` не копирует `mcp_servers/` → `poetry install` падает целиком →
`palatium_ai` не устанавливается.

**Статус: ✅ исправлено.** `mcp_servers` исключён из пакетов (`[tool.poetry]`):

```toml
packages = [
    { include = "palatium_ai", from = "src" },
#    { include = "mcp_servers" },
]
```

#### Диагностика (решает обе причины одним способом)

Проверяйте **не сборку, а образ** — сборка могла пройти «успешно»:

```powershell
# 1. Есть ли пакет внутри образа вообще?
docker run --rm --entrypoint python palatium-ai:local `
  -c "import palatium_ai; print(palatium_ai.__file__)"

# 2. Тот самый шаг entrypoint, который падает
docker run --rm --entrypoint python palatium-ai:local `
  -c "from palatium_ai.core.config import get_settings; from palatium_ai.infrastructure.database import ensure_database_and_schema; print('OK')"

# 3. Что именно сказала сборка (искать причину, а не симптом)
docker compose --env-file env/.env --profile docker-api build --progress plain api 2>&1 `
  | Select-String -Pattern 'No files found|Installing the current project|palatium_ai ->|ERROR'
```

**Пересборка после фикса** (кэш `builder` инвалидируется изменением `COPY`/`RUN`, поэтому
`--no-cache` обычно не нужен):

```powershell
make rebuild-app
```

`make rebuild-app` пересобирает и перезапускает только `api` + MCP, не трогая инфраструктуру.

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

> `dev-down.ps1` снимает только host-процессы: если 8080/8081 держат контейнеры, он
> напишет `[skip] ... not a repo process` — это ожидаемо, Docker-сторону убирает
> `docker compose rm -f` выше. `-Force` защиту не отменяет; чужое добивает только
> `-AllowForeign`, и это уносит весь Docker-стек (см. [`../START.md`](../START.md) §7).

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

**`57P03` во время рестарта больше не отдаёт `500`.** Пока Postgres поднимается, он
отвечает на новые соединения `SQLSTATE 57P03` («the database system is in recovery
mode») и рвёт соединения из пула. Слой БД (`infrastructure/database/resilience.py`)
повторяет **только получение соединения** — не сам запрос, поэтому ни один statement
не выполняется дважды. Бюджет — из конфига (050: не магические числа):

| Переменная | Default | Смысл |
|---|---|---|
| `DB_RETRY_ATTEMPTS` | `4` | всего попыток подключения; `1` — fail-fast без повторов |
| `DB_RETRY_INITIAL_DELAY_SECONDS` | `0.25` | первая пауза (дальше экспонента + jitter) |
| `DB_RETRY_MAX_DELAY_SECONDS` | `2` | верхняя граница одной паузы; она же уходит в `Retry-After` |

Когда бюджет исчерпан — или соединение не добыть из пула (`DB_POOL_TIMEOUT_SECONDS`) —
API отвечает `503` + `Retry-After: <секунды>` и пишет событие `db_unavailable` в
audit chain (035: fail-closed на границе, внутренние детали драйвера остаются в логе).
Запрос при этом не выполнялся, поэтому повтор клиента безопасен. `500` в этом
сценарии — регрессия сборки: проверьте, что образ API собран с текущим `src/`,
а не просто перезапущен:

```powershell
docker exec palatium-ai-api-1 ls /app/src/palatium_ai/infrastructure/database/resilience.py
docker exec palatium-ai-api-1 env | Select-String DB_RETRY
```

**Почему Postgres падал (и что мешает повториться).** В исходном инциденте дело было не
в самом Postgres: у контейнеров не было потолков памяти, поэтому при пиковой нагрузке
срабатывал OOM-killer *всей Docker-VM*. Он выбирает процесс с наибольшим RSS — а это
`clamd` (~1 GiB резидентных сигнатур) или `postgres`; убийство Postgres даёт
crash-recovery с многосекундными `fsync` (в логах инцидента — до 180 с) и каскад
`socket hang up` на всех HTTP-запросах.

Ограничения живут в `docker-compose.yml` (сумма — бюджет против RAM Docker-VM, 7884 MiB):

| Сервис | `mem_limit` | Почему такой |
|---|---|---|
| `postgres` | 1024m | смерть Postgres — каскадный отказ, потолок обязателен |
| `neo4j` | 1408m | 512m heap + off-heap / page cache |
| `clamav` | 1792m | сигнатуры (main+daily+bytecode) резидентно в RSS ≈1 GiB; ниже — циклический OOM |
| `litellm` | 1280m + `--num_workers 1` | каждый воркер форкает свой Prisma query-engine; форк-штор и убивал VM |
| `api` | 1152m | |
| `minio` | 448m | Go-рантайм ~200 MiB даже без нагрузки |
| `redis` | 192m | в простое ~5 MiB |
| `mcp-*`, gateway | 256m | |

Поднять потолок = снять его у соседа или дать Docker Desktop больше RAM; правка одного
числа ломает инвариант суммы (регрессионный тест `tests/unit/test_container_hardening.py`).

Там же, в `deploy/clamav/clamd-watchdog.sh`, — PID-1 надзиратель: официальный образ
запускает `clamd` отсоединённым (`clamd --foreground &`) и оставляет PID 1 = `tail`,
поэтому **мёртвый clamd не роняет контейнер**: статус остаётся `Up`, healthcheck проходит,
а каждый upload висит до таймаута скана. Обёртка владеет `/init`, опрашивает TCP-порт
`3310` и, потеряв демон *после* первой удачной готовности, гасит контейнер — дальше
срабатывает `restart: unless-stopped`. Холодный старт (freshclam) не считается сбоем.

```powershell
# потолки и OOM-статус
docker stats --no-stream --format "{{.Name}}: {{.MemUsage}} ({{.MemPerc}})"
docker inspect palatium-ai-postgres-1 --format 'oom={{.State.OOMKilled}} restarts={{.RestartCount}}'
# надзиратель на месте у clamav
docker inspect palatium-ai-clamav-1 --format '{{json .Config.Entrypoint}}'
# ожидается ["/bin/bash","/usr/local/bin/clamd-watchdog.sh"]
```

LiteLLM при холодном старте прогоняет `prisma migrate deploy` (≈2 мин) до открытия порта
4000 — поэтому у его healthcheck `start_period: 180s`; более короткий grace-период роняет
`up -d` сообщением `dependency litellm failed to start: container is unhealthy`.

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

Нужен реальный трейсинг — сначала поднимите OTLP-коллектор и trace-store, затем
укажите его HTTP-endpoint (**порт 4318**, путь `/v1/traces`):

```bash
OTEL_ENDPOINT="http://otel-collector:4318"
```

> В `deploy/observability/` trace-store **нет** (только Prometheus/Grafana/Loki —
> метрики и логи). Спан-данные туда отправлять некуда: см. комментарий в
> `grafana/provisioning/datasources/datasources.yml`. Добавление Tempo/Jaeger —
> отдельная задача. Порт 4317 — gRPC, HTTP-экспортёр его не использует.

### 3.15. `api` помечен `unhealthy` при живом `/health`

**Причина:** в healthcheck `api` указан неверный порт (`8080` вместо `8000`).

**Фикс:** в `docker-compose.yml` healthcheck `api` должен дергать
`http://127.0.0.1:8000/health`, затем:

```powershell
docker compose --env-file env/.env --profile docker-mcp --profile docker-api up -d api
docker inspect --format '{{.State.Health.Status}}' palatium-ai-api-1   # → healthy
```

### 3.16. `POST /api/attachments/*` → 503 `Attachments are disabled`

**Причина:** подсистема вложений выключена (`ATTACHMENTS_ENABLED="false"`) — роутер
отвечает 503 вместо того, чтобы принять файл «как есть» (fail-closed, 020).

```powershell
# Что реально видит контейнер
docker compose --env-file env/.env exec api env | Select-String "ATTACHMENTS_"

# Что решил composition root при старте
docker compose --env-file env/.env --profile docker-mcp --profile docker-api logs api --tail 200 |
    Select-String "Attachments disabled|Attachment ports wired|AttachmentService wired"
```

Ожидаемо при выключенной подсистеме: `Attachments disabled (ATTACHMENTS_ENABLED=false)`
и ни одной строки `AttachmentService wired`.

**Фикс:** включить и пересоздать `api` (см. §16.2 для полного набора переменных).

```powershell
docker compose --env-file env/.env --profile docker-mcp --profile docker-api up -d --force-recreate api
```

### 3.17. `api` не стартует: `RuntimeError: ATTACHMENTS_...`

Это **не баг**, а fail-closed guard'ы (020): половина конфигурации вложений — это
несканированные файлы, доходящие до модели, либо потерянные после рестарта аплоады.
Сообщение | Причина | Фикс:

| Сообщение в логе | Причина | Фикс |
|---|---|---|
| `ATTACHMENTS_BLOB_BACKEND=memory is not allowed in 'staging'` | in-process store вне `development` | `ATTACHMENTS_BLOB_BACKEND="minio"` |
| `ATTACHMENTS_SCANNER_BACKEND=disabled is not allowed in 'production'` | файлы дойдут до LLM без AV | `ATTACHMENTS_SCANNER_BACKEND="clamav"` |
| `ATTACHMENTS_MINIO_SECURE must be true in 'staging'` | креды и байты по plaintext | `ATTACHMENTS_MINIO_SECURE="true"` |
| `ATTACHMENTS_BLOB_BACKEND=minio requires ATTACHMENTS_MINIO_ACCESS_KEY and ATTACHMENTS_MINIO_SECRET_KEY` | pydantic-валидация конфига | заполнить оба секрета |
| `ATTACHMENTS_MINIO_BUCKET must not be empty` | пустое имя бакета | задать имя бакета |
| `ATTACHMENTS_SCANNER_BACKEND=clamav requires ATTACHMENTS_CLAMAV_HOST` | пустой хост сканера | задать `ATTACHMENTS_CLAMAV_HOST` |

Режим определяется переменной `ENVIRONMENT` (`development` | `staging` | `production`);
`development` — единственный, где `memory` + `disabled` разрешены.

### 3.18. MinIO / ClamAV недоступны из API

**MinIO.** Endpoint проверяется **на старте** (`ensure_bucket()`): неверный адрес/креды →
`api` не поднимается, в логе ошибка S3/MinIO. Бакет создаётся автоматически, если его нет.

```powershell
Test-NetConnection -ComputerName localhost -Port 9000

# Из контейнера: localhost = сам контейнер, для MinIO на хосте — host.docker.internal
docker compose --env-file env/.env exec api `
    python -c "import socket; socket.create_connection(('host.docker.internal', 9000), 3).close(); print('ok')"
```

**ClamAV.** Контактируется **в момент `complete`**, не при старте: мёртвый `clamd` не
ломает boot, но каждый upload получает `status="quarantined"`,
`rejection_reason="scan_failed"` (отличайте от реального детекта —
`malware_detected`, `status="quarantined"`). В логе — `attachment refused by scanner`,
в метриках — `error_type="pipeline_scan_failed"` (см. §16.7).

```powershell
Test-NetConnection -ComputerName localhost -Port 3310

# Адрес должен быть доступен ИЗ контейнера, а не только с хоста
docker compose --env-file env/.env exec api `
    python -c "import socket; socket.create_connection(('host.docker.internal', 3310), 3).close(); print('ok')"
```

> `localhost` внутри контейнера — это сам контейнер. Если MinIO/ClamAV подняты на
> хосте, используйте `host.docker.internal`; если они в той же compose-сети — имя
> сервиса (`minio`, `clamav`). clamd объявлен в `docker-compose.yml` под профилем
> `attachments`, S3-хранилище — под профилем `attachments-s3` (§16.9); внешние
> сервисы подключаются через `env/.env` (см. §16.2).

### 3.19. Redis/Valkey не стартует: `Can't handle RDB format version 12`

**Симптом:** `redis` в цикле `Restarting (1)`, `make up` падает с
`dependency failed to start: container … redis is unhealthy`, остальные сервисы живы.

**Причина:** том `palatium_ai_palatium_redis` остался от **Redis 7.4**. Valkey — форк
Redis 7.2.4 и **не читает RDB версии 12** (её пишет Redis 7.4+). При старте Valkey
разбирает AOF-base именно как RDB, не может и отказывается подниматься:

```text
* Reading RDB base file on AOF loading...
# Can't handle RDB format version 12
# Error reading the RDB base file appendonly.aof.1.base.rdb, AOF loading aborted
```

**Это не потеря данных.** В Redis лежит только эфемерное состояние: checkpoint'ы LangGraph
(TTL сессии, `session_ttl_seconds`), флаг kill-switch и состояние HITL-карточек. Содержимое
тома нечитаемо в любом случае, поэтому единственный корректный шаг — удалить несовместимый AOF.

**Фикс (одноразовый, при переходе Redis 7.4 → Valkey 8.x):**

```powershell
# Остановить только redis и снести несовместимый том
docker compose --env-file env/.env stop redis
docker rm -f palatium-ai-redis-1
docker volume rm palatium-ai_palatium_redis

# Поднять заново — Valkey создаст совместимый AOF
docker compose --env-file env/.env up -d redis

# Проверка: и healthy, и fail-closed политика на месте
docker inspect palatium-ai-redis-1 --format '{{.State.Health.Status}}'
docker exec palatium-ai-redis-1 valkey-cli config get maxmemory-policy   # → noeviction
```

> `maxmemory-policy noeviction` — не тюнинг, а часть контракта: при `allkeys-lru` ключ
> `palatium:kill_switch:engaged` может быть вытеснен под давлением, и аварийная остановка
> молча перестанет действовать (020, fail-closed). Не менять на `allkeys-*`.

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

### 5.2. Gateway latency checklist (вне репо, P2.13–14)

Источник решения: ADR `docs/adr/0001-inference-gateway-latency.md`.
В `deploy/litellm/config.yaml` уже `routing_strategy: latency-based-routing`
(P2.12) — эффект появляется, когда у одного alias **несколько** deployment.

| # | Действие на corporate gateway | Зачем |
|---|---|---|
| 1 | SGLang RadixAttention **или** vLLM continuous batching на mid/frontier | ↓ prefill / ↑ GPU util |
| 2 | Speculative decoding: draft = nano, target = mid/frontier | ↓ decode latency |
| 3 | ≥2 реплики с одним `model_name` (tier-mid и т.п.) в LiteLLM `model_list` | latency-based-routing выбирает быстрее |
| 4 | Экспорт gateway TTFT / queue depth (опционально) | метрики §5 аудита latency |

OCR vision timeout (P2.16): `ATTACHMENTS_IMAGE_OCR_TIMEOUT_SECONDS` default **30**;
чат (`/intents/process`) не ждёт OCR — только attachment ids со статусом ready.

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

### 6.1. Изоляция БД LiteLLM (отдельная БД, не `POSTGRES_DB`)

`litellm` пишет свои таблицы Prisma-migrations и держит собственный `alembic`-head.
Если он смотрит в основную БД приложения, его миграции конфликтуют с нашими: обе
системы правят одну `alembic_version`. Поэтому у gateway **своя** БД:

| Где | Ключ | Значение |
|---|---|---|
| `env/.env` (и профили) | `LITELLM_DB_URL` | `postgresql://<user>:<pw>@<host>:5432/litellm` |
| `docker-compose.yml` | env `LITELLM_DB_URL` → `deploy/litellm/config.yaml` | `general_settings.database_url: os.environ/LITELLM_DB_URL` |

```powershell
# БД litellm создаётся init-скриптом; проверить, что gateway смотрит туда
docker compose exec litellm env | Select-String LITELLM_DB_URL
docker compose exec postgres psql -U postgres -c "\l" | Select-String litellm
```

> `LITELLM_DB_URL` **обязателен** и не имеет compose-дефолта намеренно: молчаливый
> фолбэк на основную БД — это и есть баг, который он предотвращает. Пустое значение
> в `env/.env` → контейнер `litellm` не стартует (fail-closed), а не пишет в чужую БД.

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
[x] pyproject.toml: [tool.mypy] strict = true, mypy_path = ["src"], exclude содержит mcp_servers/
[x] docker-compose.yml: для всех mcp-* стоит dockerfile: mcp_servers/Dockerfile
[x] docker-compose.yml: MCP_MODULE = mcp_servers.X.Y_mcp_server
[x] .dockerignore: НЕ содержит mcp_servers/
[x] factory.py: _SUPPORTED_PROVIDERS содержит "gateway"
[x] core/config/llm/__init__.py: _SUPPORTED_PROVIDERS содержит "gateway"
[x] core/config/llm/gateway.py: существует, класс GatewayLLMConfig
[x] src/__init__.py: удалён (не нужен, вызывает конфликт mypy)
[ ] poetry check → All set!
[ ] poetry run mypy --strict src/palatium_ai → чисто (гейт scripts/ci_quality.py)
[ ] poetry run pytest tests -m "not live and not llm_live and not slow" → зелено
[ ] poetry run pytest tests/perf -m slow → нагрузочный гейт сложности (080)
[ ] docker compose --env-file env/.env config --quiet → молчит
```

Одной командой:

```powershell
poetry check
poetry run mypy --strict src/palatium_ai
poetry run pytest tests -m "not live and not llm_live and not slow"
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
| 9000 / 9001 | S3-хранилище вложений + консоль | Docker (profile `attachments-s3`, loopback) |
| 3310 | clamd (AV) для вложений | Docker (profile `attachments`, loopback) |

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

## 16. Вложения (attachments): storage, AV, TTL retention

Подсистема принимает файлы пользователя (PDF/DOCX/изображения/CSV/текст), сканирует их,
парсит и отдаёт в диалог **только фенсед-текст**; индексация в базу знаний — через
HITL-карточку. По умолчанию выключена (`ATTACHMENTS_ENABLED="false"`).

### 16.1. Где что лежит (слои 000)

| Слой | Модуль | Ответственность |
|---|---|---|
| domain | `domain/attachments/{models,types,policies,content}.py` | агрегат `Attachment`, статусы, `AttachmentIntakePolicy`, `AttachmentRetentionPolicy` — чистые функции без I/O (055) |
| ports | `domain/ports/{attachments,blob_store,document_parser,scanner}.py` | контракты репозитория, blob-store, парсера, AV |
| infrastructure | `infrastructure/blob/` (MinIO / filesystem / in-memory), `infrastructure/scanning/` (ClamAV, disabled), `infrastructure/parsing/document_parser.py`, `infrastructure/database/attachment_repository.py` | адаптеры портов |
| application | `application/services/attachment_service.py`, `application/services/attachment_pipeline.py` | use-cases + пайплайн scan→parse→injection-gate |
| presentation | `presentation/api/routers/attachments.py` (mount: `presentation/app.py` → `/api/attachments`) | HTTP |

- DI: `build_attachment_ports` / `build_attachment_limits` / `build_attachment_service`
  (`application/wiring.py`).
- БД: таблица `palatium_ai.attachments`, миграция
  `alembic/versions/a9b8c7d6e5f4_add_attachments_table.py`,
  `FORCE ROW LEVEL SECURITY` по `user_id` (060): app-роль физически не видит чужие строки.
- Ключи в хранилище: `attachments/<attachment_id>` (оригинал) и
  `attachments/<attachment_id>.text.json` (извлечённый текст). Имя файла в ключ не попадает.

### 16.2. Включение

| Переменная | Default | Смысл |
|---|---|---|
| `ATTACHMENTS_ENABLED` | `false` | мастер-выключатель; `false` → весь роутер отвечает 503 |
| `ATTACHMENTS_BLOB_BACKEND` | `memory` | `memory` \| `filesystem` (оба dev/test) \| `minio` |
| `ATTACHMENTS_FILESYSTEM_ROOT` | `.local/attachments` | корень для `filesystem` (в `.gitignore`) |
| `ATTACHMENTS_MINIO_ENDPOINT` | `localhost:9000` | адрес S3-совместимого хранилища **для API** |
| `ATTACHMENTS_MINIO_PUBLIC_ENDPOINT` | = `_ENDPOINT` | адрес, который подписывается в presigned URL для **браузера** (`http(s)://host[:port]` или `host:port`) |
| `ATTACHMENTS_MINIO_ACCESS_KEY` / `_SECRET_KEY` | — | `[SECRET]`, обязательны для `minio`; те же значения уходят в контейнер как `MINIO_ROOT_USER`/`_PASSWORD` |
| `ATTACHMENTS_MINIO_BUCKET` | `palatium-attachments` | создаётся на старте, если отсутствует |
| `ATTACHMENTS_MINIO_SECURE` | `false` | TLS; **обязан** быть `true` вне development |
| ~~`ATTACHMENTS_MINIO_IMAGE`~~ | — | **удалён**: образ store закреплён по tag+digest в `docker-compose.yml` (Silo). Значение из env молча перебивало бы пин (050); чтобы сменить store, правьте `image` сервиса `minio` |
| `ATTACHMENTS_MINIO_API_PORT` / `_CONSOLE_PORT` | `9000` / `9001` | публикуемые порты (только loopback) |
| `ATTACHMENTS_SCANNER_BACKEND` | `disabled` | `disabled` (dev/test) \| `clamav` |
| `ATTACHMENTS_CLAMAV_HOST` / `_PORT` | `localhost` / `3310` | clamd (INSTREAM) |
| `ATTACHMENTS_CLAMAV_TIMEOUT_SECONDS` | `30` | таймаут соединения и чтения ответа |
| `ATTACHMENTS_MAX_SIZE_BYTES` | `52428800` (50 MiB) | лимит размера |
| `ATTACHMENTS_MAX_PER_TURN` | `5` | лимит файлов на тред/ход **и** in-flight presigned PUT на тред (см. §16.4) |
| `ATTACHMENTS_MAX_FILENAME_CHARS` | `200` | обрезка имени с сохранением расширения |
| `ATTACHMENTS_PRESIGNED_TTL_SECONDS` | `900` | TTL presigned PUT |
| `ATTACHMENTS_ATTACH_TTL_SECONDS` | `604800` (7d) | TTL для `mode=attach`, должен переживать тред |
| `ATTACHMENTS_INDEX_RETENTION_DAYS` | `365` | TTL для `mode=index` |
| `ATTACHMENTS_MAX_PARSED_CHARS` / `_PAGES` | `2000000` / `500` | границы парсинга |
| `ATTACHMENTS_SWEEP_BATCH_SIZE` | `200` | строк за один retention-проход |
| `ATTACHMENTS_IMAGE_OCR_BACKEND` | `auto` | `disabled` \| `auto` \| `gateway` \| `tesseract`; `disabled` не подключает парсер картинок (§16.3) |
| `ATTACHMENTS_IMAGE_OCR_MODEL` | — | алиас vision-модели **в gateway** (напр. `tier-vision`); обязателен при `gateway`, опционален при `auto` |
| `ATTACHMENTS_IMAGE_OCR_MAX_BYTES` | `8388608` (8 MiB) | предел **исходных** байт, уходящих в модель (лимит приёма — 50 MiB) |
| `ATTACHMENTS_IMAGE_OCR_TIMEOUT_SECONDS` | `30` | таймаут вызова vision-модели (P2.16) |
| `ATTACHMENTS_OCR_MIN_CHARS` | `12` | quality gate: эскалация на Vision, если OCR дал меньше символов |
| `ATTACHMENTS_OCR_MIN_PRINTABLE_RATIO` | `0.55` | quality gate: эскалация при низкой доле printable-символов |
| `ATTACHMENTS_OCR_MIN_CONFIDENCE` | `55` | quality gate: эскалация при mean word confidence Tesseract ниже порога (латинский мусор с рукописной кириллицы) |
| `ATTACHMENTS_PDF_MIN_AVG_CHARS_PER_PAGE` | `200` | ниже порога PDF считается сканом → OCR-путь |
| `ATTACHMENTS_TESSERACT_CMD` | — | абсолютный путь к `tesseract`, если не в `PATH` |
| `ATTACHMENTS_PDF_VISION_MAX_PAGES` | `20` | потолок страниц PDF для vision (G14) |
| `ATTACHMENTS_PDF_FIGURE_ENRICHMENT` | `true` | VLM-дополнение страниц с фигурами при живом text layer |
| `ATTACHMENTS_PDF_FIGURE_MAX_PAGES` | `8` | soft-cap vision-вызовов на фигуры |
| `ATTACHMENTS_ANALYSIS_BACKEND` | `disabled` | `disabled` \| `local` (G15 ADA: dataframe summary CSV/XLSX под HITL) |
| `ATTACHMENTS_PII_POLICY` | `tag` | G06: `tag` (только флаг) \| `mask` (редакция в `safe_text`) \| `reject` (`pii_detected`) |

> Хранилище: `minio` — любой S3-совместимый endpoint. Собственные реестры MinIO
> **не отдают образы анонимно** — проверено 2026-09: Docker Hub `minio/minio` → denied,
> Docker Hub `minio/mc` → denied, `quay.io/minio/minio` → no such manifest,
> `ghcr.io/minio/minio` → 403, `bitnami/minio` → репозиторий пуст. Вдобавок upstream
> **заархивировал** community-редакцию (репозиторий read-only) и 2026-09-11 удалил
> `minio/minio` и `minio/mc` из Docker Hub. Прежний дефолт (`bitnamilegacy/minio`) — это
> замороженное зеркало той же мёртвой линии: он запускается, но уже никогда не получит
> security-фикс, что для runtime-зависимости запрещено (050). Поэтому профиль
> `attachments-s3` поднимает **Silo** (`pgsty/silo`) — поддерживаемый форк того же
> сервера (AGPLv3), с тем же контрактом `MINIO_ROOT_USER`/`MINIO_ROOT_PASSWORD`,
> `server /data --console-address :9001` и `/minio/health/live` (проверено на
> закреплённом дайджесте, не на словах). Образ пинится по tag+digest в
> `docker-compose.yml`; чтобы сменить store на свой реестр — правьте `image` сервиса
> `minio` там же.
> Бакет Langfuse (`langfuse`) создаёт one-shot сервис `silo-init`: у API есть
> `ensure_bucket()` на старте, у Langfuse такого вызова нет, и без бакета v3-инжест
> падает при зелёных health-эндпоинтах.
> Тем не менее локальная разработка не требует хранилища-контейнера: `filesystem`
> переживает рестарт и вторую воркер-процесс, а `memory` оставляйте тестам — он живёт
> в одном процессе, и при `UVICORN_WORKERS=2` `init` и `complete` попадают в разные
> процессы, из-за чего загрузка «теряется». Если S3 нужен именно локально — профиль
> `attachments-s3` и §16.9.
> AV: `--profile attachments` поднимает clamd локально (§16.8). Адрес хранилища и clamd
> должен быть доступен **из контейнера** API (§3.18): `host.docker.internal` для сервисов
> на хосте, имя compose-сервиса для сервисов в той же сети.
> Presigned PUT выполняет **браузер**, поэтому адрес хранилища задаётся дважды:
> `ATTACHMENTS_MINIO_ENDPOINT` — как до него дотянуться из API, `_PUBLIC_ENDPOINT` — как
> из браузера. SigV4 подписывает заголовок `Host`, поэтому готовый URL нельзя переписать
> с одного имени на другое — API подписывает сразу публичный адрес (§16.4).
> Для staging/production нужны реальный clamd и S3-совместимое хранилище с TLS (020).

### 16.3. Что принимается (закрытый реестр, 070)

`application/pdf` `.pdf` · `…wordprocessingml.document` `.docx` ·
`…spreadsheetml.sheet` `.xlsx` · `…presentationml.presentation` `.pptx` ·
`image/jpeg` `.jpg/.jpeg` · `image/png` `.png` · `image/webp` `.webp` ·
`text/csv` `.csv` · `text/html` `.html/.htm` · `text/markdown` `.md` ·
`text/plain` `.txt/.log`.

Расширение обязано совпадать с заявленным MIME. Перечень — доменная константа
`SUPPORTED_MEDIA_TYPES`; расширение = правка кода + ревью, а не настройка env.

Статусы: `pending → uploaded → scanning → ready` (успех), либо `quarantined`
(AV / инъекции), `rejected` (политика / парсинг), `expired`, `indexed`.

**Способность, а не разрешение (055).** Intake-политика проверяет не только
закрытый реестр, но и то, что для MIME реально подключён парсер. Картинки
(`image/jpeg`, `image/png`, `image/webp`) не имеют текстового слоя. При
`ATTACHMENTS_IMAGE_OCR_BACKEND=disabled` (или `auto`/`tesseract` без установленных
extras и без Vision-модели) они **отвергаются на `init`**
(`reason="mime_not_allowed"`). Default `auto`: Tesseract (если есть) → при сбое /
низком качестве — Vision encoder (`ATTACHMENTS_IMAGE_OCR_MODEL`).

**Детерминированный parse routing (не LLM).** После AV пайплайн выбирает стратегию
по MIME + плотности текстового слоя PDF (`ATTACHMENTS_PDF_MIN_AVG_CHARS_PER_PAGE`,
default 200), без классификатора:

| Вход | Стратегия |
|---|---|
| `text/*`, `docx`, `xlsx`, `pptx`, `html` | text layer |
| PDF с достаточным слоем | text layer (`pypdf`); опционально figure enrichment (VLM) |
| PDF-скан / пустой слой | **Tesseract OCR → Vision** (quality gate) → `parse_failed` |
| `image/*` | **Tesseract → Vision** (`auto`); `gateway` = Vision first |

Provenance пишется в `ParsedDocument.extraction_source` и в метрику
`palatium_attachment_parse_total{extraction_source, media_kind}`.

**Tesseract runtime.** Python-пакеты `pytesseract`/`Pillow`/`pymupdf` входят в
Poetry-группу `attachments`. Сам бинарник ставится в образ при
`WITH_ATTACHMENTS=1` (`tesseract-ocr` + `eng`/`rus` tessdata). Локально без Docker:
системный Tesseract в `PATH`, либо `ATTACHMENTS_TESSERACT_CMD` на абсолютный путь.

**Длинная вставка в чат.** Клиент (`AUTO_ATTACH_CHARS=10_000`) при paste длиннее
порога не кладёт текст в `intent.text`: создаёт `text/plain` chip
(`pasted-text_YYYY-MM-DD.txt`, `mode=attach`) и грузит через обычный
`/api/attachments` поток. В ход уходит короткий комментарий + `attachment_ids`;
индексация в knowledge — отдельно через HITL (`POST …/index`), не автоматически.

**PII на извлечённом тексте (G06).** `ATTACHMENTS_PII_POLICY`:
`tag` (default) — только `contains_pii` на derived content;
`mask` — плейсхолдеры `[EMAIL]`/`[PHONE]`/`[ID]` в `safe_text`;
`reject` — отказ `pii_detected` до admission. Детекторы — те же structured
паттерны, что у memory PII (060), без phrase-списков.

**Коннекторы (G10).** `GET /api/attachments/connectors` отдаёт каталог
(EDMS-first). Импорт из СЭД пока fail-closed (`POST …/connectors/{id}/import` →
501, `available=false`) до cutover MCP EDMS (092); Drive/SharePoint не
рекламируются как доступные. UI показывает stub-каталог над чипами.

**PII-флаг на строке.** После `complete` в metadata пишется `contains_pii`
(миграция `c2d3e4f5a6b7`); клиент показывает бейдж на chip при `ready`.

**Knowledge hybrid fusion.** `search_knowledge` сливает FTS + dense через
`KNOWLEDGE_HYBRID_FUSION`: `weighted` (default, 0.35/0.65) или `rrf`
(`KNOWLEDGE_RRF_K`, default 60). Опционально
`KNOWLEDGE_EMBEDDING_RERANK=true` — over-fetch и cosine-rerank поверх merge
(тот же knowledge embedding client; `KNOWLEDGE_EMBEDDING_RERANK_OVERFETCH`,
default 3). Cross-encoder (`sentence-transformers`) в Host не подключён —
остаётся в EDMS-legacy KB.

### 16.4. Поток загрузки

1. `POST /api/attachments/init` — intake-политика (размер, MIME↔расширение, лимит на тред,
   санитайзинг имени) → строка + presigned PUT. Audit: `attachment_init`. Отказ политики —
   400 и `palatium_agent_errors_total{error_type="intake_<reason>"}`.

   Лимит на `init` считает **только in-flight** загрузки треда: `status='pending'` с
   `created_at > now() - ATTACHMENTS_PRESIGNED_TTL_SECONDS`. Уже загруженные/готовые строки
   слот не занимают — иначе abandon’нутый presigned PUT блокировал бы тред на весь
   `ATTACHMENTS_ATTACH_TTL_SECONDS` (7d) с `turn_limit_exceeded`. Проверка и вставка строки
   выполняются в одной транзакции под `pg_advisory_xact_lock` на `(user_id, thread_id)`,
   поэтому параллельные `init` не могут проскочить лимит (race на READ COMMITTED).
   Брошенные (`pending`, тикет уже истёк) строки освобождает retention-sweep, не дожидаясь 7 дней.
2. Клиент кладёт байты в хранилище. Транспорт выбирается по схеме `upload_url`:
   - `http(s)://…` — **presigned PUT напрямую** в хранилище (API байты не видит);
   - другой scheme (`memory://`, `filesystem://`) — у хранилища нет своего HTTP-фасада,
     поэтому клиент шлёт байты в `PUT /api/attachments/{id}/content`, где API сам пишет
     объект (та же intake-политика, тот же лимит, тот же пайплайн на шаге 3).

   Прокси-вариант нужен ещё и там, где хранилище недоступно из браузера (внутренняя сеть,
   отсутствие CORS). Заголовок `Content-Length` не считается доказательством: API режет тело по
   `ATTACHMENTS_MAX_SIZE_BYTES`, читая поток (превышение → 413).

   **Два адреса хранилища.** Presigned URL подписывается на конкретный `Host` (SigV4), поэтому
   адрес в URL — это адрес, по которому браузер обязан постучаться, и подменить его
   reverse-proxy'ем или правкой строки нельзя: подпись перестанет сходиться. В compose-сети API
   видит хранилище как `minio:9000`, а браузер — как `127.0.0.1:9000`, поэтому одного значения
   не хватает:

   | Переменная | Кто ходит | Пример |
   |---|---|---|
   | `ATTACHMENTS_MINIO_ENDPOINT` | API: `stat`, `read`, `write`, `ensure_bucket` | `minio:9000` (в контейнере) |
   | `ATTACHMENTS_MINIO_PUBLIC_ENDPOINT` | браузер: presigned PUT/GET | `http://127.0.0.1:9000` |

   `_PUBLIC_ENDPOINT` принимает `http(s)://host[:port]` (схема задаёт TLS для браузера) или
   `host:port` (схема наследуется от `_SECURE`). Если не задан — оба адреса совпадают, как в
   однохостовых установках. Подписывает отдельный клиент, который никогда не делает сетевых
   вызовов: подпись — локальное вычисление, поэтому он может указывать на имя, resolv'ящееся
   только у пользователя. В логе старта видно `presign_endpoint` — именно он попадает в URL.

3. Байты в объект (альтернатива шагу 2 для больших файлов): `POST …/{id}/chunks/{index}`
   (части ≤ `ATTACHMENTS_MAX_CHUNK_BYTES`, default 8 MiB) → `POST …/{id}/chunks/finalize` с
   `chunk_count` (склейка в blob), затем шаг 4. Веб-клиент (`web/src/lib/attachments.ts`)
   на API-транспорте (`memory://` / fallback с недоступного presign) автоматически
   переключается на chunks, когда `size > UPLOAD_CHUNK_BYTES`; одиночный
   `PUT /content` остаётся для файлов ≤ 8 MiB. Presigned PUT в MinIO по-прежнему
   одним запросом.
4. `POST /api/attachments/{id}/complete` — пайплайн:
   `stat` объекта → magic-byte MIME sniff (несовпадение с заявленным → `mime_mismatch`) →
   AV-scan → (DOCX) проверка active content → парсинг с лимитами декодирования изображений →
   secret scan на извлечённом тексте → prompt-injection gate
   (`prepare_fenced_attachment`: полный scan → mask+admit при любом severity;
   только truncated scan → quarantine; текст в ход всегда в `<<<UNTRUSTED_TOOL_OUTPUT>>>`) →
   persist derived text → fencing на чтение в ход.
   Статус строки на время пайплайна — `scanning` (UI может показывать фазу до ответа).
   Audit: `attachment_completed`.
5. Файл либо участвует в ходе диалога (§16.5), либо его индексация запрашивается через HITL.
   Для ``mode=index`` клиент сначала доводит вложение до ``ready``, затем вызывает
   ``POST /api/attachments/{id}/index`` — в knowledge base ничего не пишется до approve
   карточки (отдельно от ``attach``, где текст идёт только в ход).

Отказы пайплайна:

| `rejection_reason` | Статус | Что случилось |
|---|---|---|
| `not_uploaded` | rejected | presigned PUT не состоялся, объекта нет |
| `size_invalid` / `size_exceeded` | rejected | объект пуст / превышает `ATTACHMENTS_MAX_SIZE_BYTES` |
| `mime_not_allowed` | rejected | MIME вне реестра или парсер не зарегистрирован |
| `mime_mismatch` | rejected | magic-byte sniff не совпал с заявленным MIME |
| `active_content` | rejected | макросы / OLE embeddings в OOXML (DOCX/PPTX/XLSX) |
| `image_too_large` | rejected | декодирование изображения превысило лимит пикселей |
| `pii_detected` | rejected | извлечённый текст попал под `ATTACHMENTS_PII_POLICY=reject` |
| `parse_failed` | rejected | парсер не смог извлечь текст |
| `malware_detected` | quarantined | сработала сигнатура clamd |
| `scan_failed` | quarantined | clamd недоступен/не ответил — **не** вирус (§3.18) |
| `injection_detected` | quarantined / rejected | на вложениях обычно только truncated scan; иначе mask+`ready` (fence-first, §16.4) |

На этапе `init` добавляются `filename_invalid`, `extension_mismatch`, `turn_limit_exceeded`.

### 16.5. API `/api/attachments` и инъекция в ход

| Метод и путь | Код | Назначение |
|---|---|---|
| `POST /api/attachments/init` | 201 | intake + presigned PUT; опционально `expires_in_seconds` (clamp по mode TTL) |
| `PUT /api/attachments/{id}/content` | 200 | байты через API (когда у хранилища нет HTTP-фасада или оно недоступно из браузера); 413 при превышении лимита |
| `POST /api/attachments/{id}/chunks/{index}` | 200 | resumable: одна часть blob |
| `POST /api/attachments/{id}/chunks/finalize` | 200 | склейка частей (`chunk_count`), затем нужен `/complete` |
| `POST /api/attachments/{id}/complete` | 200 | scan→parse→fence→persist |
| `GET /api/attachments?thread_id=…` | 200 | вложения треда (перед чтением — ленивый retention) |
| `GET /api/attachments/{id}` | 200 | одно вложение |
| `GET /api/attachments/{id}/download` | 200 | presigned GET оригинала (audit `attachment_download_issued`) |
| `POST /api/attachments/{id}/index` | 200 | одноразовая HITL-карточка; **ничего не пишет** |
| `POST /api/attachments/{id}/restore-request` | 200 | HITL на восстановление из карантина (`injection_detected`); approve → masked `ready` |
| `GET /api/attachments/compliance-export?thread_id=…` | 200 | JSON-сводка вложений треда (роль manager) |
| `POST /api/attachments/sweep` | 200 | retention-проход по строкам вызывающего |
| `GET /api/attachments/connectors` | 200 | каталог внешних источников (G10; EDMS stub) |
| `POST /api/attachments/connectors/{id}/import` | 501 | fail-closed до MCP EDMS import (092) |
| `DELETE /api/attachments/{id}` | 204 | строка + оба объекта |

Ошибки: 404 `AttachmentNotFoundError`; 409 `AttachmentModeMismatchError` /
`AttachmentNotUsableError`; 413 `AttachmentUploadTooLargeError` (прокси-загрузка сверх лимита);
400 прочие типизированные; 503 подсистема выключена.
Каждый запрос проверяет владельца треда (`load_session_for_principal`), и каждый запрос
к репозиторию явно несёт `user_id` (060 — RLS не отменяет явный предикат).

**Фенсинг.** Единственный путь текста вложения в диалог — `AttachmentService.build_turn_context`,
который вызывается из `application/services/intent_service.py` и кладёт фенсед-блок
(`<<<UNTRUSTED_TOOL_OUTPUT source=attachment:<filename>>>>` … `<<<END_UNTRUSTED_TOOL_OUTPUT>>>`)
в state графа (`orchestration/state.py`). Усечение по бюджету сохраняет оба маркера фенса и вставляет
`… [attachment context truncated N chars] …`, чтобы инструкция не спряталась за обрезкой.

**HITL-индексация.** `POST /{id}/index` лишь создаёт карточку (`HITLCardView.without_secrets()`);
запись в базу знаний (`platform.ingest_document`) происходит только после approve через
`/api/hitl` (`execute_after_approval`). Audit: `attachment_index_requested` → `attachment_indexed`.

**HITL-восстановление из карантина (injection).** `POST /{id}/restore-request` — только для
`status=quarantined` + `rejection_reason=injection_detected`. Approve менеджером перезапускает
пайплайн с `force_mask_injection` или маскирует уже сохранённый derived text. Audit:
`attachment_restore_requested` → `attachment_restore_approved`.

### 16.6. Retention (TTL) и sweeper

- Момент истечения: `expires_at` = now + `ATTACHMENTS_ATTACH_TTL_SECONDS` для `mode=attach`,
  + `ATTACHMENTS_INDEX_RETENTION_DAYS` для `mode=index`. `expires_at IS NULL` — строка
  не purg'ится никогда (ручное удаление владельцем).
- Ленивая рекламация: `GET /api/attachments?thread_id=…` сначала делает retention-проход для
  владельца, поэтому просроченное не показывается (и не ломает чтение при сбое — ошибка
  считается метрикой, не исключением).
- Явный per-owner проход: `POST /api/attachments/sweep` — **defense in depth** под
  `FORCE ROW LEVEL SECURITY` (app-роль не видит чужие строки).
- **SoT для глобальной очистки:** CronJob / CLI
  `poetry run python -m palatium_ai.jobs.retention --class attachment_attach|attachment_index|attachment_pii`
  через SECURITY DEFINER (`palatium_ai.retention_*`, миграция `e5f6a7b8c9d0`) + cascade
  `knowledge.retention_delete_by_attachment` и orphan-класс `knowledge_orphan` (§17).
- Один проход ограничен `ATTACHMENTS_SWEEP_BATCH_SIZE` / `RETENTION_BATCH_SIZE` (bounded: один
  залипший объект не должен превращать запрос в бесконечный цикл удалений).
- Удаляется: оригинал `attachments/<id>`, производный `attachments/<id>.text.json`, chunk parts,
  строка БД; для index — связанные `knowledge.documents` (+ chunks CASCADE).
  Если удаление объекта падает — строка **не** удаляется и попадёт в следующий проход (`failed`),
  остальные строки прохода продолжают обрабатываться.
- Отбор детерминирован: все строки прохода сравниваются с одним tz-aware UTC `now`
  (`AttachmentRetentionPolicy.is_due`), поэтому живая строка не может быть purged из-за
  пересчёта часов.
- Audit: `attachment_expired` (reason `retention_expired`); метрика `retention_sweep_failed`.

### 16.7. Наблюдаемость и проверка

| Audit-событие | Когда |
|---|---|
| `attachment_init` | выдан presigned URL |
| `attachment_received` | байты приняты через `PUT /{id}/content` (прокси-загрузка) |
| `attachment_completed` | пайплайн завершён |
| `attachment_deleted` | удаление владельцем |
| `attachment_expired` | TTL-purge |
| `attachment_index_requested` | создана HITL-карточка |
| `attachment_indexed` | запись в базу знаний после approve |
| `attachment_download_issued` | выдан presigned GET оригинала |
| `attachment_restore_requested` | создана HITL-карточка восстановления |
| `attachment_restore_approved` | карантин снят, текст замаскирован, `ready` |

Метрики: `palatium_agent_errors_total{agent_type="attachments", error_type=…}`, где
`error_type` ∈ `intake_<reason>` · `pipeline_<reason>` · `retention_sweep_failed` ·
`retention_sweep_read_path_failed`; плюс
`palatium_attachment_parse_total{extraction_source, media_kind}` на успешный parse
(`extraction_source` ∈ `text_layer|vision|ocr|none`, `media_kind` ∈ `image|pdf|text|office|other`).

```powershell
# Распределение статусов и причин отказов
docker compose exec postgres psql -U postgres -d postgres -c "SELECT status, rejection_reason, count(*) FROM palatium_ai.attachments GROUP BY 1, 2 ORDER BY 3 DESC;"

# Кандидаты на retention (UTC)
docker compose exec postgres psql -U postgres -d postgres -c "SELECT id, mode, status, expires_at FROM palatium_ai.attachments WHERE expires_at IS NOT NULL AND expires_at <= now() ORDER BY expires_at LIMIT 20;"

# Хвост решений пайплайна
docker compose --env-file env/.env --profile docker-mcp --profile docker-api logs api --tail 200 |
    Select-String "attachment refused|attachment.retention_sweep|AttachmentService wired"
```

Smoke-сценарий: `init` → `PUT` байтов по `upload_url` (или `PUT /{id}/content`, если схема
не `http(s)`) → `complete` (ждём `status="ready"`) → `sweep`. Все вызовы — с JWT вызывающего
и его собственным `thread_id`.

### 16.8. Локальный запуск, веб-интерфейс и терминальные примеры

Минимум для локальной проверки (host-профиль Poetry, `START.md` §4): в `env/.env`
поставить `ATTACHMENTS_ENABLED="true"` и `ATTACHMENTS_BLOB_BACKEND="filesystem"`
(каталог `ATTACHMENTS_FILESYSTEM_ROOT`, по умолчанию `.local/attachments`, в `.gitignore`).
`memory` для этого сценария не годится при `UVICORN_WORKERS=2` — см. врезку в §16.2.

AV локально поднимается отдельным профилем (в обычном `up` clamd не стартует):

```powershell
make attach-up                       # = --profile attachments up -d clamav
# затем в env/.env: ATTACHMENTS_SCANNER_BACKEND="clamav", ATTACHMENTS_CLAMAV_HOST="localhost"
docker compose --env-file env/.env --profile attachments up -d clamav   # то же самое вручную
```

**Одна команда на ядро + вложения:** `make up` (в меню — STACK → *Start stack*).
Он поднимает базовый стек вместе с профилем `attachments`, а `attachments-s3` добавляет
**только если образ хранилища доступен** (preflight, §16.9) — недоступный S3 не должен
ронять уже работающий AV-путь. Профиль решает, какие контейнеры *запустить*, но не чем
пользуется API: поэтому запуск идёт с оверлеями `docker-compose.attachments-av.yml` /
`docker-compose.attachments-s3.yml`, чей `environment:` перебивает `env_file: env/.env` и
переключает `ATTACHMENTS_SCANNER_BACKEND`/`ATTACHMENTS_BLOB_BACKEND` на clamav/minio.
Набор флагов (профили **и** `-f`-оверлеи) целиком вычисляет
`attachments_probe.py --compose-args` — та же функция, что печатает режим
(`--mode --full`), поэтому «что подняли» и «чем пользуемся» не разъезжаются.
Для S3 оверлей и профиль включаются/выключаются только вместе: API не может быть
переключён на контейнер, который не стартовал. Если образ хранилища недоступен,
оверлей S3 не грузится, и `--mode --full` печатает `blob_backend=filesystem` плюс причину.

`make up` (и `make attach-*`) эти оверлеи **не** грузят: обычный dev остаётся на
`filesystem`/`disabled` из `env/.env`, а CLI/SDK-путь Poetry — на тех же значениях.

S3-хранилище локально не нужно вовсе; если оно всё же требуется — отдельный профиль
`attachments-s3` и обязательный preflight образа (`make attach-s3-up`, §16.9).
Проверить, что из трёх компонентов живо: `make attach-probe` (§16.9).

Первый старт clamd занимает минуты (загрузка сигнатур в volume `palatium_clamav_db`).
До готовности движка сканы падают fail-closed: `rejection_reason="scan_failed"`,
статус `quarantined` — это **не** вирус (§3.18). Порт публикуется только на loopback
(`127.0.0.1:${ATTACHMENTS_CLAMAV_PORT}`): у INSTREAM нет аутентификации, поэтому наружу
его выставлять нельзя. API-контейнер получает `ATTACHMENTS_CLAMAV_HOST=clamav`
(compose DNS), host-профиль — `localhost` из `env/.env`.

Полный цикл руками (PowerShell, dev-JWT):

```powershell
$base  = "http://127.0.0.1:8000/api"
$token = (Invoke-RestMethod -Method Post "$base/auth/dev-token" -ContentType application/json `
    -Body '{"user_id":"user-dev","org_id":"org-default"}').access_token
$h = @{ Authorization = "Bearer $token" }

# 1) intake: политика + presigned URL
$file = Get-Item .\docs\runbook.md
$init = Invoke-RestMethod -Method Post "$base/attachments/init" -Headers $h -ContentType application/json `
    -Body (@{
        thread_id  = "thread-dev-1"
        filename   = $file.Name
        mime_type  = "text/markdown"
        size_bytes = $file.Length
        mode       = "attach"
    } | ConvertTo-Json)

# 2) байты: напрямую в хранилище либо прокси через API (по схеме upload_url)
if ($init.upload_url -match '^https?://') {
    Invoke-RestMethod -Method Put $init.upload_url -InFile $file.FullName `
        -Headers @{ "Content-Type" = "text/markdown" }   # без Authorization: подпись уже в URL
} else {
    Invoke-RestMethod -Method Put "$base/attachments/$($init.attachment_id)/content" `
        -Headers $h -InFile $file.FullName -ContentType "text/markdown"
}

# 3) пайплайн: ждём status="ready"
Invoke-RestMethod -Method Post "$base/attachments/$($init.attachment_id)/complete" -Headers $h

# 4) ход диалога с вложением
Invoke-RestMethod -Method Post "$base/intents/process" -Headers $h -ContentType application/json `
    -Body (@{
        text           = "О чём этот файл?"
        thread_id      = "thread-dev-1"
        attachment_ids = @($init.attachment_id)
    } | ConvertTo-Json)
```

Отказы видны сразу и типом, и текстом:

```powershell
# чужой/несуществующий id в ходу -> 404, а не тихое игнорирование
Invoke-RestMethod -Method Post "$base/intents/process" -Headers $h -ContentType application/json `
    -Body '{"text":"summary","thread_id":"thread-dev-1","attachment_ids":["11111111-2222-3333-4444-555555555555"]}'
# недопустимый MIME на intake -> 400 intake_mime_not_allowed
# тело больше ATTACHMENTS_MAX_SIZE_BYTES -> 413 (режется на чтении тела)
```

Веб-интерфейс: `npm run dev` в `web/` (Vite на `:5173`, `/api` проксируется на `:8000`).
В композере есть скрепка и drag&drop; чипы показывают путь `uploading → ready`, а отказ —
с причиной (`blocked: malware detected`, `blocked: antivirus unavailable`,
`file type is not accepted`, …).

**Контракт композера (2026, как ChatGPT / Claude / Gemini):** чип в композере —
только staging до send. После успешного хода ready-чипы снимаются; файл остаётся
на пузыре user-сообщения. Follow-up без повторной загрузки опирается на историю
диалога (ответ/OCR уже в prior), а не на «вечный» чип над полем ввода. Новый файл
на следующем ходе — единственный в `attachment_ids` этого хода. Неудачные чипы
остаются, чтобы видеть причину и повторить. `mode=attach` на сервере живёт
`ATTACHMENTS_ATTACH_TTL_SECONDS` (§16.6); ContinuityPolicy при непустом
`untrusted_context` не биндит workers на prior format (иначе «сводка по файлу»
переписывает OCR предыдущего вложения).

### 16.9. Локальное S3-хранилище (профиль `attachments-s3`)

Локально хранилище-контейнер **не обязателен**: `ATTACHMENTS_BLOB_BACKEND="filesystem"`
переживает рестарт и вторую воркер-процесс (§16.2) и не требует ни реестра, ни кредов.
Профиль нужен, когда проверяется именно S3-путь: presigned PUT из браузера, поведение
`ensure_bucket`, TTL объектов.

**Состояние реестров (перепроверено 2026-09, `docker manifest inspect`).**
Официальные образы MinIO не отдаются анонимно ни из одного своего реестра:

| Ссылка | Ответ |
|---|---|
| `minio/minio` (Docker Hub) | denied — требуется аутентификация |
| `minio/mc` (Docker Hub) | denied |
| `quay.io/minio/minio` | no such manifest (любой тег, включая `:latest`) |
| `quay.io/minio/mc` | no such manifest |
| `ghcr.io/minio/minio` | 403 |
| `bitnami/minio` | репозиторий пуст (0 тегов) |
| `bitnamilegacy/minio:2024.12.18-debian-12-r0` | OK — но это зеркало мёртвой линии (upstream архивирован), security-фиксов не будет |
| **`pgsty/silo:RELEASE.2026-09-16T00-00-00Z`** | **OK — текущий дефолт профиля (поддерживаемый форк)** |

Контрольная проверка метода: на тех же запросах `clamav/clamav:1.5.4-debian` отдаётся
анонимно, то есть отказы выше — именно ограничение доступа, а не блокировка клиента.
Практический вывод: **образ MinIO надо брать из maintained-источника** — поэтому `image`
сервиса `minio` закреплён в `docker-compose.yml` на Silo по tag+digest (050). Профиль
`attachments-s3` по-прежнему отделён от `attachments`: недоступный образ не должен ломать
уже работающий AV-путь, поэтому подъём идёт через preflight:

```powershell
# 1. Свой реестр: правка `image` сервиса `minio` в docker-compose.yml (tag + digest).
make attach-s3-up     # preflight образа (image читается из compose) -> up -d minio
# либо из меню: ATTACHMENTS -> Start S3 store (preflight встроен)
#
# Сразу с ядром стека: make up / меню STACK -> Start stack —
# они добавляют attachments-s3 ровно тогда, когда preflight образа прошёл,
# и вместе с ним грузят docker-compose.attachments-s3.yml, который и переключает
# API на minio (иначе контейнер поднят, но «вхолостую», §16.8).
```

Если preflight вернул FAIL — это проблема доступа к реестру, а не compose; локально
разумнее не тратить на неё время и остаться на `filesystem`.

**Что не нужно делать.** Бакет создавать руками не надо: `build_attachment_ports` вызывает
`ensure_bucket()` на старте и создаёт его при отсутствии. Неверный адрес или креды роняют
`api` на boot, а не первый upload (020). Соответственно нет и шага «зайти в консоль и создать
bucket» — если `api` поднялся, бакет уже есть. Единственное исключение — бакет Langfuse
(`langfuse`): он нужен профилю `observability`, у Langfuse своего `ensure_bucket` нет,
поэтому его создаёт one-shot сервис `silo-init` (у него в образе есть `mc`). Конкуренция за создание безопасна: воркеры
поднимаются одновременно, и проигравший гонку получает `BucketAlreadyOwnedByYou`, что
трактуется как успех (иначе процесс падал бы на штатной гонке — см. регрессионный тест
`test_minio_ensure_bucket_tolerates_the_startup_create_race`).

Что `silo-init` отработал, проверяет `attachments_probe.py` (проба `silo-init`): успех —
`Exited (0)`, то есть «контейнер не запущен» здесь штатно, а провал bootstrap'а иначе
незаметен — см. «Единая диагностика» ниже.

**Про `exec` в контейнере.** Дефолтный образ — Debian-based Bitnami-сборка, поэтому шелл в
нём **есть**, и листинг бакета работает без отдельного контейнера:

```powershell
docker exec palatium-ai-minio-1 mc ls local/
```

**Два адреса — обязательное условие.** Контейнеру API хранилище видно как `minio:9000`
(compose переопределяет `ATTACHMENTS_MINIO_ENDPOINT`), а браузеру — как `127.0.0.1:9000`
(опубликованный loopback-порт). `ATTACHMENTS_MINIO_PUBLIC_ENDPOINT` должен указывать на
второй адрес, и именно **литералом `127.0.0.1`**, а не `localhost`: порт опубликован только
на IPv4-loopback (020 — наружу не смотрит), а Windows резолвит `localhost` в `::1` первым
и тратит ~2 с на фолбэк в IPv4 — то есть на каждом presigned PUT. Измерено на этом стенде:
`localhost:9000` → 2072 мс, `127.0.0.1:9000` → 2 мс на коннект (типичный presigned PUT:
2.07 с → 0.01 с). Иначе presigned PUT подписывается на недостижимый `Host`
(например `minio:9000`), браузер такой хост не резолвит, и строка навсегда остаётся
в `pending`. Переписать URL после подписи нельзя — SigV4 покрывает заголовок `Host`
(§16.4). Проверить, что подставилось:

```powershell
docker compose --env-file env/.env --profile docker-api --profile attachments-s3 config `
  | Select-String "ATTACHMENTS_MINIO"
# ожидается: ENDPOINT=minio:9000, PUBLIC_ENDPOINT=http://127.0.0.1:9000
# при старте api в логе: BlobStorePort: MinIO … presign_endpoint=http://127.0.0.1:9000
```

**Креды.** Значения `ATTACHMENTS_MINIO_ACCESS_KEY` / `_SECRET_KEY` уходят в контейнер как
`MINIO_ROOT_USER` / `MINIO_ROOT_PASSWORD` — один источник истины вместо дублирующей пары
переменных. Пароль короче 8 символов MinIO не примет; `make attach-s3-up` проверяет это до
`up`, чтобы не поднимать контейнер с нерабочими кредами. Порт консоли опубликован только на
loopback: своей авторизации, кроме root-кредов, у неё нет, а они кластерные (020).

**Единая диагностика.** `make attach-probe` (или пункт `Probe attachments` в меню) проверяет
компоненты по отдельности и печатает, что именно лежит:

```powershell
python scripts/attachments_probe.py            # API /health, clamd zPING, S3 /minio/health/live, silo-init
python scripts/attachments_probe.py --preflight-image   # только проверка образа
```

Проверка clamd — не TCP-connect, а `zPING` с ожиданием `PONG`: clamd принимает соединение
до загрузки сигнатур, и «порт открыт» не значит, что скан пройдёт (§16.4, `scan_failed`).

**Проверка `silo-init`.** One-shot bootstrap обязан завершиться с кодом 0, и probe это
проверяет отдельной пробой. Ломается он незаметно: `api` создаёт свой бакет сам, поэтому
упавший bootstrap выглядит здоровым стеком, а `langfuse`-бакета при этом нет — и v3-инжест
уходит в пустоту при зелёных health-эндпоинтах. Что важно при чтении статуса:

- «не запущен» / `Exited (0)` у `silo-init` — **штатное** конечное состояние, а не сбой
  (поэтому же readiness живёт в probe, а не в `docker compose up --wait`);
- разовые контейнеры от `docker compose run silo-init` в вердикт не берутся: probe
  отбирает только управляемый контейнер (`com.docker.compose.oneoff=False`), иначе ручной
  прогон с ненулевым кодом заваливал бы `make up`;
- при `--skip-s3` проба пропускается вместе с остальными проверками store — этот флаг
  помечает прогон, который init-контейнер не пересоздаёт (`make rebuild-app`).

---

## 17. Global retention (CronJob / CLI)

**Полный гайд (env, классы, расписание, диагностика):**
[`global-retention.md`](global-retention.md).

План: [`.cursor/plans/global-retention.md`](../.cursor/plans/global-retention.md).
ADR: [`adr/0002-global-retention-scheduler.md`](adr/0002-global-retention-scheduler.md).

Кратко:

- Entrypoint: `poetry run python -m palatium_ai.jobs.retention`
- Default — **dry-run**. Destructive: `--execute` или `RETENTION_EXECUTE=true`.
- Окна: `RETENTION_*` в `env/.env.example` §10b (и `env/.env`); SoT —
  `RetentionConfig` / `RetentionWindows` / `RetentionPolicy`.
- Миграции: `d4e5f6a7b8c9` (memory RPCs) · `e5f6a7b8c9d0` (attachments/knowledge/checkpoint grants).
- Реализованные DB-classes: `session_transcript`, `memory_*`, `checkpointer`,
  `attachment_*`, `knowledge_orphan`. Остальное — policy snapshot / W4–W6.
- Attachments: global cron = SoT; lazy/`POST /sweep` (§16.6) — defense.

```powershell
# After: poetry run alembic upgrade head
poetry run python -m palatium_ai.jobs.retention --list-classes
poetry run python -m palatium_ai.jobs.retention --class report_only
poetry run python -m palatium_ai.jobs.retention --class memory_medium --class session_transcript
poetry run python -m palatium_ai.jobs.retention --class checkpointer --class attachment_attach
# destructive (staging only after dry-run review):
# poetry run python -m palatium_ai.jobs.retention --execute --class session_transcript
# poetry run python -m palatium_ai.jobs.retention --execute --class memory_pii
# poetry run python -m palatium_ai.jobs.retention --execute --class attachment_index
# poetry run python -m palatium_ai.jobs.retention --execute --class knowledge_orphan
```

---

## См. также

- [`../START.md`](../START.md) — старт: setup, `$PROFILE`, три режима
- [`docker.md`](docker.md) — пошаговый запуск Docker-профиля и troubleshooting
- [`handbook.md`](handbook.md) — полный путь от clone до ops
- [`ops-readiness.md`](ops-readiness.md) — чеклист staging/prod
- [`secrets.md`](secrets.md) — секреты / Vault / CI
- [`global-retention.md`](global-retention.md) — настройки и использование global retention
- [`.cursor/plans/global-retention.md`](../.cursor/plans/global-retention.md) — волны W0–W6 retention

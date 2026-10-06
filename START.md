# 📘 Palatium-AI — START

Единый стартовый документ. Универсальная инструкция (Windows).
Замените `D:\project\palatium-ai` на актуальный путь.

**Содержание:**
1. [Требования](#1-требования)
2. [Первоначальная настройка](#2-первоначальная-настройка)
3. [$PROFILE — быстрые команды](#3-profile--быстрые-команды)
4. [Режим A — Host-профиль](#4-режим-a--host-профиль-ежедневная-разработка)
5. [Режим B — Docker-профиль](#5-режим-b--docker-профиль-ci--демо)
6. [Режим C — Gateway-профиль](#6-режим-c--gateway-профиль-тест-политик-mcp)
7. [Остановка](#7-остановка)
8. [Архитектура](#8-архитектура)
9. [Диагностика](#9-быстрая-диагностика)
10. [Типичные проблемы](#10-типичные-проблемы)
11. [Чек-лист первого запуска](#11-чек-лист-первого-успешного-запуска)
12. [Шпаргалка команд](#12-шпаргалка-команд)
13. [Смена модели для tier'а](#13-смена-модели-для-tiera)
14. [Ежедневный workflow](#14-ежедневный-workflow)
15. [Переезд на другой ПК](#15-переезд-на-другой-пк)

---

## 1. Требования

| Компонент | Версия | Проверка |
|---|---|---|
| Docker Desktop | Running | `docker version` |
| Docker Compose | v2+ | `docker compose version` |
| Poetry | 2.x | `poetry --version` |
| Python | 3.14 | `poetry env info` |

```powershell
docker version; docker compose version; poetry --version
```

---

## 2. Первоначальная настройка

### 2.1. Клонировать и перейти

```powershell
git clone <repo-url> D:\project\palatium-ai
cd D:\project\palatium-ai
```

### 2.2. Создать `env/.env`

```powershell
Copy-Item env\.env.example env\.env
```

**Минимум, что заполнить:**

```bash
# ---- App DB ----
POSTGRES_USER="postgres"
POSTGRES_PASSWORD="1234"
POSTGRES_DB="postgres"            # ← именно postgres, НЕ palatium_dev
POSTGRES_SCHEMA="palatium_ai"
POSTGRES_PUBLISH_PORT=5432        # 5433, если на хосте уже есть локальный Postgres

# ---- Gateway (LiteLLM) ----
LITELLM_MASTER_KEY="sk-palatium-master"
LITELLM_PUBLISH_PORT=4000
PALATIUM_GATEWAY_KEY=""           # сгенерировать: .\scripts\litellm-provision-key.ps1

# ---- Провайдер (по умолчанию — corporate Qwen) ----
QWEN_API_KEY="corporate-llm"
QWEN_BASE_URL="http://model-generative.shared.du.iba/v1"
QWEN_DEFAULT_MODEL="generative-model"
```

> **`POSTGRES_DB=postgres` — это правильно.** Alembic создаёт **схемы** внутри
> (`palatium_ai`, `edms_assistant`, `knowledge`, `memory`), а не отдельную БД.
> Отдельная БД нужна только для Langfuse (`langfuse`).

### 2.3. Установить зависимости

```powershell
poetry install --with dev
```

### 2.4. Разрешить запуск скриптов

```powershell
Set-ExecutionPolicy -Scope CurrentUser RemoteSigned
```

### 2.5. Проверить критичный fix в коде

```powershell
Select-String -Path src\palatium_ai\infrastructure\llm\factory.py -Pattern "_SUPPORTED_PROVIDERS"
```

**Должно быть:**

```python
_SUPPORTED_PROVIDERS: frozenset[str] = frozenset({"openai", "anthropic", "ollama", "qwen", "gateway"})
```

Если `"gateway"` нет — добавить. Без этого API падает с
`ValueError: No usable LLM providers in chain starting with 'gateway'`.

### 2.6. Проверить `mcp_servers`

MCP stubs — обычные Python-модули в `mcp_servers/` (пакет с `__init__.py` +
подпапки). Они **намеренно НЕ входят** в пакет `palatium_ai` и **не** указаны
в `[tool.poetry].packages`: у них отдельный образ
(`mcp_servers/Dockerfile`, `PYTHONPATH=/app/src:/app`), а на хосте они
запускаются из корня репозитория. См. блок `NOTE` в корневом `Dockerfile`.

**Проверка файлов:**

```powershell
@(
  "mcp_servers\__init__.py",
  "mcp_servers\edms\__init__.py",
  "mcp_servers\analytics\__init__.py",
  "mcp_servers\gateway\__init__.py",
  "mcp_servers\platform\__init__.py"
) | ForEach-Object { "$([bool](Test-Path $_))  $_" }
```

**Проверка `pyproject.toml`** — в списке пакетов должен быть только
`palatium_ai` (строка `mcp_servers` закомментирована осознанно):

```powershell
Select-String -Path pyproject.toml -Pattern "packages|mcp_servers"
```

**Импорт-тест** (запускать из корня репозитория):

```powershell
poetry run python -c "import mcp_servers; from mcp_servers.edms import edms_mcp_server; print('OK')"
```

### 2.7. Выбрать режим работы

В проекте **три режима**, которые **нельзя смешивать** (конфликт по портам 8080/8081):

| Режим | MCP где | API где | Gateway-слой |
|---|---|---|---|
| **Host** (ежедневно) | Poetry (host) | Poetry (host) | нет |
| **Docker** (CI/демо) | Docker | Docker | нет |
| **Gateway** (тест политик) | Poetry (host) | Poetry (host) | **есть** (8090/8091) |

В корне уже лежит `docker-compose.override.yml` (если его нет — создайте):

```yaml
# docker-compose.override.yml
services:
  mcp-edms:
    profiles: ["docker-mcp"]
  mcp-analytics:
    profiles: ["docker-mcp"]
  mcp-gateway-edms:
    profiles: ["mcp-gateway"]
  mcp-gateway-analytics:
    profiles: ["mcp-gateway"]
  api:
    profiles: ["docker-api"]
```

**Проверка:**

```powershell
docker compose config --services
# Ожидаем: postgres, redis, neo4j, litellm
```

> **Зачем это нужно:** без `override.yml` любой `docker compose up -d`
> (без явного списка сервисов) поднимет **все** сервисы, включая
> `mcp-edms`, `mcp-analytics`, `api`. Это создаст конфликт портов
> с host-профилем (Poetry, :8080/:8081/:8000). `override.yml` физически
> не даёт этому случиться.

---

## 3. `$PROFILE` — быстрые команды

### 3.1. Открыть профиль

```powershell
notepad $PROFILE
```

### 3.2. Полный блок для `$PROFILE`

Скопируйте целиком в **конец** файла:

```powershell
# =============================================================================
# Palatium-AI — PowerShell profile commands
# =============================================================================

# -----------------------------------------------------------------------------
# 0. Настройки окружения
# -----------------------------------------------------------------------------
$env:COMPOSE_ENV_FILES = "env/.env"
$script:PalatiumRoot = "D:\project\palatium-ai"

# -----------------------------------------------------------------------------
# 1. Навигация
# -----------------------------------------------------------------------------
function palatium-cd {
    Set-Location $script:PalatiumRoot
}

function palatium-scripts {
    Set-Location (Join-Path $script:PalatiumRoot "scripts")
}

# -----------------------------------------------------------------------------
# 2. Запуск / остановка (host-профиль через Poetry)
# -----------------------------------------------------------------------------
function palatium-up {
    & "$script:PalatiumRoot\scripts\dev-up.ps1" @args
}

function palatium-down {
    & "$script:PalatiumRoot\scripts\dev-down.ps1" @args
}

function palatium-status {
    & "$script:PalatiumRoot\scripts\dev-status.ps1" @args
}

function palatium-menu {
    & "$script:PalatiumRoot\scripts\menu.ps1" @args
}

function palatium-up-gw {
    & "$script:PalatiumRoot\scripts\dev-up.ps1" -WithGateway @args
}

function palatium-up-mcp {
    & "$script:PalatiumRoot\scripts\dev-up.ps1" -SkipApi @args
}

function palatium-up-full {
    & "$script:PalatiumRoot\scripts\dev-up.ps1" -WithGateway -WithPlatformStub @args
}

# -----------------------------------------------------------------------------
# 3. Docker Compose — короткие обёртки
# -----------------------------------------------------------------------------
function dcompose {
    docker compose @args
}

function palatium-infra-up {
    docker compose up -d postgres redis neo4j litellm
}

function palatium-infra-down {
    docker compose stop postgres redis neo4j litellm
}

function palatium-infra-reset {
    Write-Host "Reset Docker infra + volumes..." -ForegroundColor Yellow
    docker compose down -v
    Write-Host "Done. Теперь: palatium-infra-up" -ForegroundColor Green
}

function palatium-docker-ps {
    docker compose ps
}

function palatium-docker-logs {
    param([string]$Service = "")
    if ($Service) {
        docker compose logs -f $Service
    } else {
        docker compose logs -f
    }
}

function palatium-build {
    # palatium-build            → runtime-образ palatium-ai:local (default)
    # palatium-build api        → то же, явное имя
    # palatium-build test       → образ с pytest    (--target test)
    # palatium-build devtools   → shell + Poetry    (--target devtools)
    param(
        [ValidateSet("api", "test", "devtools")]
        [string]$Target = "api"
    )
    Push-Location $script:PalatiumRoot
    try {
        switch ($Target) {
            "api"      {
                Write-Host "Building palatium-ai:local (runtime)..." -ForegroundColor Cyan
                docker build -t palatium-ai:local .
            }
            "test"     {
                Write-Host "Building palatium-ai:test..." -ForegroundColor Cyan
                docker build --target test -t palatium-ai:test .
            }
            "devtools" {
                Write-Host "Building palatium-ai:devtools..." -ForegroundColor Cyan
                docker build --target devtools -t palatium-ai:devtools .
            }
        }
    } finally {
        Pop-Location
    }
    if ($LASTEXITCODE -eq 0) {
        Write-Host "OK. Проверка: docker images palatium-ai" -ForegroundColor Green
    } else {
        Write-Host "Build failed (exit $LASTEXITCODE)" -ForegroundColor Red
    }
}

# Полный Docker-стек (профили docker-mcp + docker-api).
# ВАЖНО: включать ОБА профиля — api.depends_on ссылается на mcp-edms/mcp-analytics,
# иначе "invalid compose project". См. docs/runbook.md §3.11.
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

# Диагностический отчёт (docs/runbook.md §13): логи + конфиги + redaction секретов
function palatium-diag {
    & "$script:PalatiumRoot\scripts\diag-report.ps1" @args
}

# -----------------------------------------------------------------------------
# 4. Health-check'и
# -----------------------------------------------------------------------------
function palatium-health {
    $checks = @(
        @{ Name = "API";               Url = "http://127.0.0.1:8000/health" },
        @{ Name = "LiteLLM";           Url = "http://127.0.0.1:4000/health/liveliness" },
        @{ Name = "MCP EDMS";          Url = "http://127.0.0.1:8080/health" },
        @{ Name = "MCP Analytics";     Url = "http://127.0.0.1:8081/health" },
        @{ Name = "Gateway EDMS";      Url = "http://127.0.0.1:8090/health" },
        @{ Name = "Gateway Analytics"; Url = "http://127.0.0.1:8091/health" },
        @{ Name = "Platform";          Url = "http://127.0.0.1:8082/health" }
    )
    Write-Host ""
    Write-Host "Palatium-AI health" -ForegroundColor Cyan
    Write-Host ""
    foreach ($c in $checks) {
        try {
            $r = Invoke-WebRequest -Uri $c.Url -TimeoutSec 2 -UseBasicParsing -ErrorAction Stop
            Write-Host ("  {0,-20} {1}" -f $c.Name, "OK $($r.StatusCode)") -ForegroundColor Green
        } catch {
            Write-Host ("  {0,-20} {1}" -f $c.Name, "--") -ForegroundColor DarkGray
        }
    }
    Write-Host ""
}

# -----------------------------------------------------------------------------
# 5. LiteLLM — модели + тестовый запрос
# -----------------------------------------------------------------------------
function palatium-models {
    $key = "sk-palatium-master"
    try {
        $r = Invoke-RestMethod -Uri "http://127.0.0.1:4000/v1/models" `
            -Headers @{ Authorization = "Bearer $key" } -TimeoutSec 5
        Write-Host ""
        Write-Host "LiteLLM tier models:" -ForegroundColor Cyan
        foreach ($m in $r.data) {
            Write-Host "  • $($m.id)" -ForegroundColor Green
        }
        Write-Host ""
    } catch {
        Write-Host "LiteLLM недоступен: $($_.Exception.Message)" -ForegroundColor Red
    }
}

function palatium-test {
    param(
        [string]$Tier = "tier-mid",
        [string]$Message = "Say OK"
    )
    # curl.exe + JSON через escape-последовательность backtick
    $json = "{`"model`":`"$Tier`",`"messages`":[{`"role`":`"user`",`"content`":`"$Message`"}]}"

    Write-Host ""
    Write-Host "Testing $Tier..." -ForegroundColor Cyan

    $sw = [System.Diagnostics.Stopwatch]::StartNew()
    $result = curl.exe -s -S http://127.0.0.1:4000/v1/chat/completions `
        -H "Authorization: Bearer sk-palatium-master" `
        -H "Content-Type: application/json" `
        --max-time 300 `
        -d $json
    $sw.Stop()

    Write-Host "Time: $([Math]::Round($sw.Elapsed.TotalSeconds, 2))s" -ForegroundColor Yellow
    try {
        $r = $result | ConvertFrom-Json
        Write-Host "model:   $($r.model)" -ForegroundColor Green
        Write-Host "content: $($r.choices[0].message.content)" -ForegroundColor Green
        Write-Host "tokens:  $($r.usage.total_tokens)" -ForegroundColor Gray
    } catch {
        Write-Host $result -ForegroundColor Red
    }
    Write-Host ""
}

# -----------------------------------------------------------------------------
# 6. БД
# -----------------------------------------------------------------------------
function palatium-dbs {
    docker compose exec postgres psql -U postgres -c "\l"
}

function palatium-schemas {
    docker compose exec postgres psql -U postgres -d postgres -c "\dn"
}

function palatium-extensions {
    docker compose exec postgres psql -U postgres -d postgres -c "\dx"
}

function palatium-psql {
    param([string]$Db = "postgres")
    docker compose exec postgres psql -U postgres -d $Db
}

function palatium-migrations {
    docker compose exec api alembic upgrade head
}

function palatium-alembic-version {
    docker compose exec postgres psql -U postgres -d postgres `
        -c "SELECT version_num FROM palatium_ai.alembic_version;"
}

# -----------------------------------------------------------------------------
# 7. Логи host-стека
# -----------------------------------------------------------------------------
function palatium-logs-api {
    Get-Content "$script:PalatiumRoot\scripts\.dev\logs\palatium-ai.stderr.log" -Tail 50 -Wait
}

function palatium-logs-api-out {
    Get-Content "$script:PalatiumRoot\scripts\.dev\logs\palatium-ai.stdout.log" -Tail 50 -Wait
}

function palatium-logs-edms {
    Get-Content "$script:PalatiumRoot\scripts\.dev\logs\mcp-edms.stderr.log" -Tail 50 -Wait
}

function palatium-logs-analytics {
    Get-Content "$script:PalatiumRoot\scripts\.dev\logs\mcp-analytics.stderr.log" -Tail 50 -Wait
}

function palatium-logs-gateway-edms {
    Get-Content "$script:PalatiumRoot\scripts\.dev\logs\mcp-gateway-edms.stderr.log" -Tail 50 -Wait
}

function palatium-logs-gateway-analytics {
    Get-Content "$script:PalatiumRoot\scripts\.dev\logs\mcp-gateway-analytics.stderr.log" -Tail 50 -Wait
}

function palatium-logs-all {
    $logDir = "$script:PalatiumRoot\scripts\.dev\logs"
    if (-not (Test-Path $logDir)) {
        Write-Host "Нет логов: $logDir" -ForegroundColor Yellow
        return
    }
    Write-Host "Tail 20 строк каждого лога:" -ForegroundColor Cyan
    Get-ChildItem "$logDir\*.stderr.log" | ForEach-Object {
        Write-Host ""
        Write-Host "=== $($_.Name) ===" -ForegroundColor Yellow
        Get-Content $_.FullName -Tail 20 -ErrorAction SilentlyContinue
    }
}

# -----------------------------------------------------------------------------
# 8. UI
# -----------------------------------------------------------------------------
function palatium-ui          { Start-Process "http://127.0.0.1:8000/docs" }
function palatium-ui-litellm  { Start-Process "http://127.0.0.1:4000/ui" }
function palatium-ui-neo4j    { Start-Process "http://127.0.0.1:7474" }

function palatium-ui-all {
    palatium-ui
    palatium-ui-litellm
    palatium-ui-neo4j
}

# -----------------------------------------------------------------------------
# 9. Порты
# -----------------------------------------------------------------------------
function palatium-ports {
    $ports = @(
        @{ Port = 8000; Name = "API" },
        @{ Port = 8080; Name = "MCP EDMS" },
        @{ Port = 8081; Name = "MCP Analytics" },
        @{ Port = 8082; Name = "MCP Platform" },
        @{ Port = 8090; Name = "Gateway EDMS" },
        @{ Port = 8091; Name = "Gateway Analytics" },
        @{ Port = 4000; Name = "LiteLLM" },
        @{ Port = 5432; Name = "Postgres" },
        @{ Port = 5433; Name = "Postgres (alt)" },
        @{ Port = 6379; Name = "Redis" },
        @{ Port = 7474; Name = "Neo4j HTTP" },
        @{ Port = 7687; Name = "Neo4j Bolt" }
    )
    Write-Host ""
    Write-Host "Palatium-AI ports" -ForegroundColor Cyan
    Write-Host ""
    foreach ($p in $ports) {
        $conn = Get-NetTCPConnection -LocalPort $p.Port -State Listen -ErrorAction SilentlyContinue |
            Select-Object -First 1
        if ($conn) {
            Write-Host ("  :{0,-5} {1,-20} pid={2}" -f $p.Port, $p.Name, $conn.OwningProcess) -ForegroundColor Green
        } else {
            Write-Host ("  :{0,-5} {1,-20} —" -f $p.Port, $p.Name) -ForegroundColor DarkGray
        }
    }
    Write-Host ""
}

# -----------------------------------------------------------------------------
# 10. Рестарт
# -----------------------------------------------------------------------------
function palatium-restart {
    palatium-down -Force
    palatium-up @args
}

function palatium-restart-gw {
    palatium-down -Force
    palatium-up-gw @args
}

# -----------------------------------------------------------------------------
# 11. Помощь
# -----------------------------------------------------------------------------
function palatium-help {
    Write-Host ""
    Write-Host "Palatium-AI — доступные команды" -ForegroundColor Cyan
    Write-Host ""
    Write-Host "Навигация:" -ForegroundColor Yellow
    Write-Host "  palatium-cd, palatium-scripts"
    Write-Host ""
    Write-Host "Запуск / остановка:" -ForegroundColor Yellow
    Write-Host "  palatium-up              # API + MCP (direct)"
    Write-Host "  palatium-up-gw           # + gateway :8090/8091"
    Write-Host "  palatium-up-mcp          # только MCP stubs"
    Write-Host "  palatium-up-full         # gateway + platform"
    Write-Host "  palatium-down [-Force]"
    Write-Host "  palatium-restart / palatium-restart-gw"
    Write-Host "  palatium-status / palatium-menu"
    Write-Host ""
    Write-Host "Docker:" -ForegroundColor Yellow
    Write-Host "  palatium-infra-up / palatium-infra-down / palatium-infra-reset"
    Write-Host "  palatium-docker-ps / palatium-docker-logs [service]"
    Write-Host "  palatium-build [api|test|devtools]   # docker build образа API"
    Write-Host "  palatium-docker-up / palatium-docker-down   # полный стек (оба профиля)"
    Write-Host "  palatium-docker-build [services] [-NoCache]"
    Write-Host "  palatium-diag            # diag-report.txt (логи + конфиги, секреты вырезаны)"
    Write-Host "  dcompose <args>"
    Write-Host ""
    Write-Host "Проверки:" -ForegroundColor Yellow
    Write-Host "  palatium-health / palatium-ports / palatium-models"
    Write-Host "  palatium-test [tier]"
    Write-Host ""
    Write-Host "БД:" -ForegroundColor Yellow
    Write-Host "  palatium-dbs / palatium-schemas / palatium-extensions"
    Write-Host "  palatium-psql [db] / palatium-migrations / palatium-alembic-version"
    Write-Host ""
    Write-Host "Логи:" -ForegroundColor Yellow
    Write-Host "  palatium-logs-api / palatium-logs-api-out"
    Write-Host "  palatium-logs-edms / palatium-logs-analytics"
    Write-Host "  palatium-logs-gateway-edms / palatium-logs-gateway-analytics"
    Write-Host "  palatium-logs-all"
    Write-Host ""
    Write-Host "UI:" -ForegroundColor Yellow
    Write-Host "  palatium-ui / palatium-ui-litellm / palatium-ui-neo4j / palatium-ui-all"
    Write-Host ""
}

# -----------------------------------------------------------------------------
# 12. Legacy run.ps1 (если файл существует)
# -----------------------------------------------------------------------------
$runScript = Join-Path $script:PalatiumRoot "run.ps1"
if (Test-Path $runScript) {
    function dev          { & $runScript dev @args }
    function staging      { & $runScript staging @args }
    function prod         { & $runScript prod @args }
    function init         { & $runScript init @args }
    function install-deps { & $runScript install @args }
    function prj-help     { & $runScript help @args }
}

# =============================================================================
# Конец блока Palatium-AI
# =============================================================================
```

### 3.3. Загрузить и проверить

```powershell
. $PROFILE
Get-Command palatium-*
$env:COMPOSE_ENV_FILES
palatium-help
```

---

## 4. Режим A — Host-профиль (ежедневная разработка)

### Шаг 1 — Поднять инфраструктуру в Docker

```powershell
cd D:\project\palatium-ai
docker compose up -d postgres redis neo4j litellm
```

Проверить:

```powershell
docker compose ps
```

Ожидаем — 4 сервиса **healthy**:
```
palatium-ai-postgres-1   Up (healthy)   0.0.0.0:5432->5432/tcp
palatium-ai-redis-1      Up (healthy)   0.0.0.0:6379->6379/tcp
palatium-ai-neo4j-1      Up (healthy)   0.0.0.0:7474->7474/tcp, 0.0.0.0:7687->7687/tcp
palatium-ai-litellm-1    Up (healthy)   0.0.0.0:4000->4000/tcp
```

> Не запускайте `docker compose up -d` без списка сервисов — это попытается поднять
> MCP/API в Docker и создаст конфликт портов с host-стеком.

### Шаг 2 — Остановить старые host-процессы

```powershell
.\scripts\dev-down.ps1 -Force
```

### Шаг 3 — Поднять host-стек (Poetry)

```powershell
.\scripts\dev-up.ps1
```

**Что запустится:**

| Сервис | URL |
|---|---|
| palatium-ai API | http://127.0.0.1:8000/docs |
| MCP EDMS stub | http://127.0.0.1:8080/health |
| MCP Analytics stub | http://127.0.0.1:8081/health |

### Шаг 4 — Проверить

```powershell
.\scripts\dev-status.ps1
```

### Шаг 5 — Открыть UI

| UI | URL | Логин / Пароль |
|---|---|---|
| Swagger | http://127.0.0.1:8000/docs | — |
| LiteLLM | http://127.0.0.1:4000/ui | `admin` / `sk-palatium-master` |
| Neo4j | http://127.0.0.1:7474 | `neo4j` / `palatium-neo4j` |

---

## 5. Режим B — Docker-профиль (CI / демо)

```powershell
# 1. Убить host-процессы
.\scripts\dev-down.ps1 -Force

# 2. Поднять всё в Docker
docker compose --profile docker-mcp --profile docker-api up -d --build

# 3. Проверить
docker compose ps
```

> **`dev-up.ps1` в этом режиме не используйте** — host и Docker MCP stubs конфликтуют по портам.

Изменения кода:

```powershell
docker compose --profile docker-mcp --profile docker-api up -d --build api
```

---

## 6. Режим C — Gateway-профиль (тест политик MCP)

Gateway-слой (`mcp_servers/gateway/`) — прокси перед upstream stubs. Нужен для проверки:
- `pin_allowlist` — белый список инструментов
- `pin_filter` — фильтрация по пин-коду
- `upstream_policy` — правила пересылки

```
API :8000
    │ MCP_SERVERS={"edms":"http://127.0.0.1:8090"}
    ▼
Gateway EDMS :8090
    │ MCP_UPSTREAM_URL=http://127.0.0.1:8080
    ▼
Upstream EDMS :8080
```

### Запуск

```powershell
.\scripts\dev-down.ps1 -Force
.\scripts\dev-up.ps1 -WithGateway
```

**Что запустится:**

| Сервис | URL | Роль |
|---|---|---|
| API | http://127.0.0.1:8000 | Ходит на 8090/8091 |
| Gateway EDMS | http://127.0.0.1:8090 | Проксирует на 8080 |
| Gateway Analytics | http://127.0.0.1:8091 | Проксирует на 8081 |
| MCP EDMS (upstream) | http://127.0.0.1:8080 | Реальный stub |
| MCP Analytics (upstream) | http://127.0.0.1:8081 | Реальный stub |

### Проверка gateway

```powershell
curl http://127.0.0.1:8090/health
curl http://127.0.0.1:8091/health

$body = '{"jsonrpc":"2.0","id":1,"method":"tools/list"}'

Invoke-RestMethod -Uri "http://127.0.0.1:8090/mcp" `
    -Method Post `
    -Headers @{
        Authorization  = "Bearer dev-mcp-local-token"
        "Content-Type" = "application/json"
    } `
    -Body $body |
    ConvertTo-Json -Depth 5

Get-Content scripts\.dev\logs\mcp-gateway-edms.stderr.log -Wait
```

### Дополнительно: platform stub

```powershell
.\scripts\dev-up.ps1 -WithGateway -WithPlatformStub
```

---

## 7. Остановка

```powershell
# Host-профиль (режимы A/C)
.\scripts\dev-down.ps1
.\scripts\dev-down.ps1 -Force

# Docker-стек
docker compose down

# Полный reset (удалить volumes)
docker compose down -v
```

---

## 8. Архитектура

### LLM-стек

```
┌─────────────────────────────────────────────────────────┐
│  Palatium-AI (host, Poetry) :8000                       │
│  PALATIUM_GATEWAY_URL=http://127.0.0.1:4000             │
│  TIER_* → "tier-nano" / "tier-mid" / ...                │
└─────────────────────┬───────────────────────────────────┘
                      │ HTTP
                      ▼
┌─────────────────────────────────────────────────────────┐
│  LiteLLM Gateway (Docker) :4000                         │
│  deploy/litellm/config.yaml                             │
│                                                         │
│  tier-nano     → ${TIER_NANO_MODEL}     + API_KEY       │
│  tier-small    → ${TIER_SMALL_MODEL}    + API_KEY       │
│  tier-mid      → ${TIER_MID_MODEL}      + API_KEY       │
│  tier-frontier → ${TIER_FRONTIER_MODEL} + API_KEY       │
│  tier-deep     → ${TIER_DEEP_MODEL}     + API_KEY       │
└─────────────────────┬───────────────────────────────────┘
                      │ HTTP (OpenAI-compatible)
                      ▼
              ┌───────────────────────┐
              │ Qwen corporate        │
              │ Qwen3.6-35B-A3B-FP8   │
              │ 128K ctx              │
              └───────────────────────┘
```

**Приложение не знает, какая модель за `tier-*`.** Меняете провайдера для tier'а — правите
`docker-compose.yml` → `litellm.environment` + `docker compose up -d --force-recreate litellm`.

### MCP-слой

```
API :8000
    │ MCP_SERVERS
    ▼
Direct:  edms :8080  /  analytics :8081
Gateway: gateway-edms :8090 → edms :8080
         gateway-analytics :8091 → analytics :8081
```

---

## 9. Быстрая диагностика

> Полный разбор по симптомам (фиксы, сеть, volumes, ядерный сброс) — в
> [`docs/runbook.md`](docs/runbook.md). Ниже — минимум для старта.
> Автосбор отчёта: `.\scripts\diag-report.ps1`.

```powershell
Write-Host "=== Poetry ===" -ForegroundColor Cyan
(Get-Command poetry).Source

Write-Host "`n=== factory.py: _SUPPORTED_PROVIDERS ===" -ForegroundColor Cyan
Select-String -Path src\palatium_ai\infrastructure\llm\factory.py -Pattern "_SUPPORTED_PROVIDERS"

Write-Host "`n=== pyproject.toml: packages ===" -ForegroundColor Cyan
Select-String -Path pyproject.toml -Pattern "packages|mcp_servers"

Write-Host "`n=== COMPOSE_ENV_FILES ===" -ForegroundColor Cyan
if ($env:COMPOSE_ENV_FILES) { Write-Host "  OK: $env:COMPOSE_ENV_FILES" -ForegroundColor Green }
else { Write-Host "  НЕ ЗАДАН → добавьте в `$PROFILE" -ForegroundColor Yellow }

Write-Host "`n=== MCP stubs (пакет) ===" -ForegroundColor Cyan
@(
  "mcp_servers\__init__.py",
  "mcp_servers\edms\edms_mcp_server.py",
  "mcp_servers\edms\__init__.py",
  "mcp_servers\analytics\analytics_mcp_server.py",
  "mcp_servers\analytics\__init__.py",
  "mcp_servers\gateway\gateway_mcp_server.py",
  "mcp_servers\gateway\__init__.py"
) | ForEach-Object {
  $m = if (Test-Path $_) { "OK " } else { "НЕТ" }
  Write-Host "  $m  $_"
}

Write-Host "`n=== Импорт из Poetry venv ===" -ForegroundColor Cyan
poetry run python -c "
import sys
print('python:', sys.executable)
try:
    import fastmcp; print('fastmcp:', fastmcp.__version__)
except Exception as e: print('fastmcp FAIL:', e)
try:
    import palatium_ai; print('palatium_ai:', palatium_ai.__file__)
except Exception as e: print('palatium_ai FAIL:', e)
try:
    import mcp_servers; print('mcp_servers:', mcp_servers.__file__)
except Exception as e: print('mcp_servers FAIL:', e)
" 2>&1

Write-Host "`n=== Порты ===" -ForegroundColor Cyan
@(8000, 8080, 8081, 8082, 8090, 8091, 5432, 5433, 6379, 4000, 7474, 7687) | ForEach-Object {
  $conn = Get-NetTCPConnection -LocalPort $_ -State Listen -ErrorAction SilentlyContinue
  if ($conn) { Write-Host ("  :{0,-5} pid={1}" -f $_, $conn.OwningProcess) -ForegroundColor Green }
  else       { Write-Host ("  :{0,-5} —" -f $_) -ForegroundColor DarkGray }
}

Write-Host "`n=== Docker ps ===" -ForegroundColor Cyan
docker compose ps

Write-Host "`n=== stderr palatium-ai ===" -ForegroundColor Cyan
Get-Content scripts\.dev\logs\palatium-ai.stderr.log -Tail 30 -ErrorAction SilentlyContinue

Write-Host "`n=== stdout palatium-ai ===" -ForegroundColor Cyan
Get-Content scripts\.dev\logs\palatium-ai.stdout.log -Tail 30 -ErrorAction SilentlyContinue
```

---

## 10. Типичные проблемы

> Канонический перечень симптом → фикс — [`docs/runbook.md`](docs/runbook.md) §3
> (там же «профильные» грабли `no such service`). Здесь — только частые кейсы.

### ❌ Конфликт портов 8080 / 8081 (host MCP vs Docker MCP)

```
Error response from daemon: ports are not available:
exposing port TCP 127.0.0.1:8081: bind: Only one usage of each socket address
```

**Фикс** — использовать один режим (§2.7):

```powershell
.\scripts\dev-down.ps1 -Force
docker compose rm -f mcp-edms mcp-analytics mcp-gateway-edms mcp-gateway-analytics
docker compose up -d postgres redis neo4j litellm
.\scripts\dev-up.ps1
```

### ❌ `docker compose exec` требует `--env-file`

```powershell
$env:COMPOSE_ENV_FILES = "env/.env"
. $PROFILE
```

### ❌ `failed to read env/.env: line N: unexpected character "\\"`

В `.env` попали команды PowerShell. Очистить:

```powershell
Copy-Item env\.env env\.env.backup
$clean = Get-Content env/.env | Where-Object {
    $_ -match '^\s*#' -or
    $_ -match '^\s*$' -or
    $_ -match '^\s*[A-Za-z_][A-Za-z0-9_]*\s*='
}
$clean | Set-Content env/.env -Encoding UTF8
```

### ❌ `POSTGRES_PASSWORD is missing a value`

Проверить `env/.env` и `$env:COMPOSE_ENV_FILES`.

### ❌ `ValueError: No usable LLM providers in chain starting with 'gateway'`

```python
_SUPPORTED_PROVIDERS: frozenset[str] = frozenset({"openai", "anthropic", "ollama", "qwen", "gateway"})
```

### ❌ `palatium-ai did not bind port 8000 within 90s`

```powershell
Get-Content scripts\.dev\logs\palatium-ai.stderr.log -Tail 30
Get-Content scripts\.dev\logs\palatium-ai.stdout.log -Tail 30
```

| Что в логе | Фикс |
|---|---|
| `No usable LLM providers... 'gateway'` | §2.5 |
| `asyncpg... connect failed` | Сверить `POSTGRES_PUBLISH_PORT` |
| `ModuleNotFoundError: mcp_servers` | §2.6 + `poetry install --with dev` |
| Пусто / висит | Увеличить `-StartupTimeoutSeconds` |

### ❌ `palatium_dev does not exist`

Это нормально. Всё в `postgres`:

```powershell
docker compose exec postgres psql -U postgres -d postgres -c "\dn"
```

### ❌ Postgres `bind: address already in use`

```bash
POSTGRES_PUBLISH_PORT=5433
```

```powershell
docker compose up -d --force-recreate postgres
```

### ❌ LiteLLM `health: starting` дольше минуты

```powershell
docker compose logs litellm --tail 50
```

### ❌ `Response ended prematurely` при `Invoke-RestMethod`

PowerShell `Invoke-RestMethod` плохо работает с chunked-ответами LiteLLM. Использовать `curl.exe`:

```powershell
$json = '{"model":"tier-mid","messages":[{"role":"user","content":"Say OK"}]}'

$masterKey = $env:LITELLM_MASTER_KEY
curl.exe -s -S http://127.0.0.1:4000/v1/chat/completions `
  -H "Authorization: Bearer $masterKey" `
  -H "Content-Type: application/json" `
  --max-time 300 `
  -d $json
```

### ❌ `Invalid JSON payload: unexpected character`

PowerShell передаёт `\"` буквально. Использовать одинарные кавычки:

```powershell
# Правильно:
$json = '{"model":"tier-mid","messages":[{"role":"user","content":"Say OK"}]}'

# Неправильно (bash-стиль):
curl.exe ... -d '{\"model\":\"tier-mid\",...}'
```

### ❌ Corporate LLM недоступна из Docker

```powershell
# IP Docker
docker compose exec litellm python -c "import urllib.request; print(urllib.request.urlopen('https://api.ipify.org').read().decode())"

# IP хоста
curl -s https://api.ipify.org
```

Если совпадают — whitelist пропускает. Если разные — прокси или LiteLLM на хост.

### ❌ Изменения в `.env` не подхватываются

```powershell
docker compose up -d --force-recreate <service>
```

### ❌ Функции `palatium-*` не найдены

```powershell
. $PROFILE
Get-Command palatium-*
```

### ❌ `Cannot overwrite variable PID because it is read-only`

Заменить `$pid` на `$ownerPid` или `$procId`.

### ❌ `Missing closing '}' in statement block`

```powershell
$null = [System.Management.Automation.Language.Parser]::ParseFile(
    (Resolve-Path .\scripts\dev-up.ps1).Path,
    [ref]$null, [ref]$errors
)
if ($errors) { $errors | Format-Table -AutoSize } else { "OK" }
```

### ❌ `Source file found twice under different module names`

```toml
[tool.mypy]
mypy_path = ["src"]
exclude = ["tests/", "build/", "dist/", ".venv/"]
```

---

## 11. Чек-лист первого успешного запуска

```
[ ] 1.  Docker Desktop — Running
[ ] 2.  Poetry: poetry --version → 2.x
[ ] 3.  env/.env заполнен (POSTGRES_PASSWORD, LITELLM_*, QWEN_*)
[ ] 4.  poetry install --with dev
[ ] 5.  Set-ExecutionPolicy -Scope CurrentUser RemoteSigned
[ ] 6.  $PROFILE содержит palatium-* + COMPOSE_ENV_FILES=env/.env
[ ] 7.  factory.py содержит "gateway" в _SUPPORTED_PROVIDERS
[ ] 8.  mcp_servers/ содержит __init__.py (в pyproject packages только palatium_ai)
[ ] 9.  docker-compose.override.yml на месте (профили docker-mcp/docker-api)
[ ] 10. docker compose config --services → 4 сервиса
[ ] 11. docker compose up -d postgres redis neo4j litellm — успешно
[ ] 12. docker compose ps — 4 healthy
[ ] 13. .\scripts\dev-down.ps1 -Force
[ ] 14. .\scripts\dev-up.ps1 — без ошибок
[ ] 15. .\scripts\dev-status.ps1 — всё OK
[ ] 16. curl http://127.0.0.1:8000/health → {"status":"ok"}
[ ] 17. curl http://127.0.0.1:4000/health/liveliness → "I'm alive!"
[ ] 18. curl.exe http://127.0.0.1:4000/v1/models → 5 tier'ов
[ ] 19. Тест tier-mid через curl.exe → ответ от Qwen
[ ] 20. Swagger http://127.0.0.1:8000/docs открывается
[ ] 21. (опц.) .\scripts\dev-up.ps1 -WithGateway → 8090/8091 healthy
```

---

## 12. Шпаргалка команд

### Запуск / остановка

| Задача | Команда |
|---|---|
| Инфра в Docker | `docker compose up -d postgres redis neo4j litellm` |
| Host-стек | `.\scripts\dev-up.ps1` |
| Только MCP stubs | `.\scripts\dev-up.ps1 -SkipApi` |
| С platform stub | `.\scripts\dev-up.ps1 -WithPlatformStub` |
| **С gateway** | `.\scripts\dev-up.ps1 -WithGateway` |
| Docker-профиль | `docker compose --profile docker-mcp --profile docker-api up -d --build` |
| Остановить host | `.\scripts\dev-down.ps1` (или `-Force`) |
| Остановить Docker | `docker compose down` |
| Полный reset | `docker compose down -v` |

### С `$PROFILE`

```powershell
palatium-cd / palatium-scripts
palatium-up / palatium-up-gw / palatium-up-mcp / palatium-up-full
palatium-down [-Force]
palatium-restart / palatium-restart-gw
palatium-status / palatium-menu
palatium-build api
palatium-docker-up / palatium-docker-down
palatium-docker-build [services] [-NoCache]
palatium-diag
palatium-infra-up / palatium-infra-down / palatium-infra-reset
palatium-docker-ps / palatium-docker-logs [service]
palatium-health / palatium-ports / palatium-models / palatium-test [tier]
palatium-dbs / palatium-schemas / palatium-extensions
palatium-psql [db] / palatium-migrations / palatium-alembic-version
palatium-logs-api / palatium-logs-api-out
palatium-logs-edms / palatium-logs-analytics
palatium-logs-gateway-edms / palatium-logs-gateway-analytics
palatium-logs-all
palatium-ui / palatium-ui-litellm / palatium-ui-neo4j / palatium-ui-all
palatium-help
```

### Проверки endpoints

```powershell
curl http://127.0.0.1:8000/health
curl http://127.0.0.1:4000/health/liveliness
curl http://127.0.0.1:8080/health
curl http://127.0.0.1:8081/health
curl http://127.0.0.1:8090/health
curl http://127.0.0.1:8091/health

curl.exe -H "Authorization: Bearer sk-palatium-master" http://127.0.0.1:4000/v1/models

$json = '{"model":"tier-mid","messages":[{"role":"user","content":"Say OK"}]}'
$masterKey = $env:LITELLM_MASTER_KEY
curl.exe -s -S http://127.0.0.1:4000/v1/chat/completions `
  -H "Authorization: Bearer $masterKey" `
  -H "Content-Type: application/json" `
  --max-time 300 `
  -d $json
```

### БД

```powershell
docker compose exec postgres psql -U postgres -c "\l"
docker compose exec postgres psql -U postgres -d postgres -c "\dn"
docker compose exec postgres psql -U postgres -d postgres -c "\dx"
docker compose exec postgres psql -U postgres -d postgres -c "SELECT version_num FROM palatium_ai.alembic_version;"
docker compose exec postgres psql -U postgres -c "CREATE DATABASE langfuse;"
```

### Диагностика

> Полный runbook: [`docs/runbook.md`](docs/runbook.md).

| Задача | Команда |
|---|---|
| Статус | `.\scripts\dev-status.ps1` |
| Отчёт для разбора | `.\scripts\diag-report.ps1` |
| Docker ps | `docker compose ps` |
| Логи API | `Get-Content scripts\.dev\logs\palatium-ai.stderr.log -Tail 50` |
| Логи Gateway | `Get-Content scripts\.dev\logs\mcp-gateway-edms.stderr.log -Tail 50` |
| Логи LiteLLM | `docker compose logs litellm --tail 50` |
| Порт занят | `Get-NetTCPConnection -LocalPort <порт> -State Listen` |
| Синтаксис скрипта | `$null = [Parser]::ParseFile((Resolve-Path .\scripts\dev-up.ps1).Path, [ref]$null, [ref]$err); $err` |

---

## 13. Смена модели для tier'а

Всё в `docker-compose.yml` → сервис `litellm` → `environment`:

```yaml
TIER_MID_MODEL: "openai/gpt-4o"
TIER_MID_API_KEY: ${OPENAI_API_KEY}
TIER_MID_API_BASE: ${OPENAI_BASE_URL}
TIER_MID_TIMEOUT: "60"
```

Применить:

```powershell
docker compose up -d --force-recreate litellm
docker compose exec litellm env | Select-String "TIER_MID"
```

### Сценарии

| Сценарий | MODEL | API_KEY | API_BASE |
|---|---|---|---|
| Qwen corporate | `openai/generative-model` | `${QWEN_API_KEY}` | `${QWEN_BASE_URL}` |
| Ollama Cloud | `openai/gpt-oss:20b-cloud` | `${OLLAMA_API_KEY}` | `https://ollama.com/v1` |
| OpenAI | `openai/gpt-4o` | `${OPENAI_API_KEY}` | `${OPENAI_BASE_URL}` |
| Anthropic | `anthropic/claude-sonnet-4-5` | `${ANTHROPIC_API_KEY}` | `${ANTHROPIC_BASE_URL}` |

---

## 14. Ежедневный workflow

```powershell
# Утро
docker compose up -d postgres redis neo4j litellm
.\scripts\dev-up.ps1
.\scripts\dev-status.ps1

# Работа: http://127.0.0.1:8000/docs

# Тест gateway (когда нужно)
.\scripts\dev-down.ps1 -Force
.\scripts\dev-up.ps1 -WithGateway

# Вечер
.\scripts\dev-down.ps1
docker compose down
```

**С `$PROFILE`:**

```powershell
palatium-infra-up
palatium-up
palatium-status
palatium-down
```

---

## 15. Переезд на другой ПК

1. Установить: Docker Desktop, Poetry, Python 3.14
2. Клонировать: `git clone <repo> D:\project\palatium-ai`
3. Создать `.env`: `Copy-Item env\.env.example env\.env` + заполнить (§2.2)
4. Проверить порт 5432: если занят — `POSTGRES_PUBLISH_PORT=5433`
5. `poetry install --with dev`
6. `Set-ExecutionPolicy -Scope CurrentUser RemoteSigned`
7. Настроить `$PROFILE` (§3)
8. Проверить `factory.py` — `"gateway"` в `_SUPPORTED_PROVIDERS` (§2.5)
9. Проверить `mcp_servers/` + `pyproject.toml` (§2.6)
10. Проверить `docker-compose.override.yml` (§2.7)
11. Запустить по §4 (Режим A)
12. Проверить по чек-листу §11

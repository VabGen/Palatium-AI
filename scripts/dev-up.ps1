#Requires -Version 5.1
<#
.SYNOPSIS
  Start palatium-ai app and remote MCP stubs for development (Poetry-host profile).

.DESCRIPTION
  Локальный запуск (НЕ в Docker):
    - EDMS MCP stub        http://127.0.0.1:8080
    - Analytics MCP stub   http://127.0.0.1:8081
    - Gateway EDMS         http://127.0.0.1:8090   (opt-in: -WithGateway)
    - Gateway Analytics    http://127.0.0.1:8091   (opt-in: -WithGateway)
    - Platform MCP stub    http://127.0.0.1:8082   (opt-in: -WithPlatformStub)
    - palatium-ai API      http://127.0.0.1:8000

  Требует, чтобы Docker-стек (Postgres, Redis, LiteLLM) был уже поднят:
    docker compose --env-file env/.env up -d postgres redis litellm

  Скрипт сам:
    • читает env/.env → POSTGRES_PUBLISH_PORT / REDIS_PUBLISH_PORT / LITELLM_PUBLISH_PORT;
    • проверяет, что Docker-стек доступен на этих портах;
    • выставляет ENV_FILE, MCP_SERVERS, PALATIUM_GATEWAY_URL для хоста;
    • запускает MCP stubs и API через Poetry;
    • сохраняет PID в scripts/.dev/processes.json.

  Поведение при занятых портах:
    • если процесс живой и отвечает на health → [skip]
    • если это НАШ процесс (из этого репо) и он мёртв → [kill] и запуск нового
    • если порт держит чужой процесс (обычно порт-прокси Docker на 8080/8081) →
      ошибка с указанием владельца; чужое не убивается (см. lib/dev-common.ps1)

.PARAMETER SkipApi
  Запустить только MCP stubs (без palatium-ai на :8000).

.PARAMETER SkipDockerCheck
  Не проверять, что Docker-стек (Postgres/Redis/LiteLLM) поднят.

.PARAMETER AllowNoGateway
  Продолжить запуск API, даже если LiteLLM недоступен. По умолчанию старт
  отменяется: без gateway любой турн падает, а в UI это маскируется под ошибку
  формата (напр. `formatter_output_invalid`) — см. Assert-DockerStackUp.
  Проверка срабатывает только когда LLM реально идёт через gateway: при
  LLM_DEFAULT_PROVIDER="qwen" (прямой корпоративный endpoint) LiteLLM не нужен,
  и флаг не требуется.

.PARAMETER WithPlatformStub
  Дополнительно поднять platform stub на :8082.

.PARAMETER WithGateway
  Дополнительно поднять gateway-слой (proxy) на :8090 (EDMS) и :8091 (Analytics).
  При этом API будет обращаться к MCP-серверам через gateway, а не напрямую.
  Требует, чтобы upstream stubs (8080/8081) были запущены — они стартуют первыми.

.PARAMETER EnvFile
  Какой env-файл использовать. По умолчанию env/.env.

.EXAMPLE
  .\scripts\dev-up.ps1
  .\scripts\dev-up.ps1 -SkipApi -WithPlatformStub
  .\scripts\dev-up.ps1 -WithGateway
  .\scripts\dev-up.ps1 -WithGateway -WithPlatformStub
  .\scripts\dev-up.ps1 -EnvFile env/.env.dev
#>

[CmdletBinding()]
param(
    [switch]$SkipApi,
    [switch]$SkipDockerCheck,
    # Explicit opt-out from the LiteLLM preflight. Off by default: a turn without the
    # gateway fails in a way that looks like a formatter bug (see Assert-DockerStackUp).
    [switch]$AllowNoGateway,
    [switch]$WithPlatformStub,
    [switch]$WithGateway,
    [string]$EnvFile = "env/.env"
)

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

# =============================================================================
# Пути
# =============================================================================
$RepoRoot  = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
$DevDir    = Join-Path $PSScriptRoot ".dev"
$LogDir    = Join-Path $DevDir "logs"
$StateFile = Join-Path $DevDir "processes.json"
$EnvPath   = Join-Path $RepoRoot $EnvFile

New-Item -ItemType Directory -Force -Path $LogDir | Out-Null

# Ownership rule for the dev ports. Shared with dev-down.ps1 so the two scripts cannot
# drift apart on what counts as "our" process — see the file header.
. (Join-Path $PSScriptRoot "lib/dev-common.ps1")

# =============================================================================
# Хелперы
# =============================================================================
function Test-CommandAvailable {
    param([Parameter(Mandatory = $true)][string]$Name)
    return [bool](Get-Command $Name -ErrorAction SilentlyContinue)
}

function Get-PortListener {
    param([Parameter(Mandatory = $true)][int]$Port)
    $conn = Get-NetTCPConnection -LocalPort $Port -State Listen -ErrorAction SilentlyContinue |
        Select-Object -First 1
    if (-not $conn) { return $null }
    return [pscustomobject]@{ pid = [int]$conn.OwningProcess; port = $Port }
}

function Test-PortListening {
    param([Parameter(Mandatory = $true)][int]$Port)
    return [bool](Get-PortListener -Port $Port)
}

function Get-PoetryExe {
    if (-not (Test-CommandAvailable "poetry")) {
        throw "poetry not found in PATH. Install Poetry and run from repo root."
    }
    return (Get-Command poetry).Source
}

function Read-DotEnv {
    param([Parameter(Mandatory = $true)][string]$Path)
    $map = @{}
    if (-not (Test-Path $Path)) { return $map }
    foreach ($raw in Get-Content -Path $Path) {
        $line = $raw.Trim()
        if (-not $line) { continue }
        if ($line.StartsWith("#")) { continue }
        $idx = $line.IndexOf("=")
        if ($idx -lt 1) { continue }
        $k = $line.Substring(0, $idx).Trim()
        $v = $line.Substring($idx + 1).Trim()
        if ($v.Length -ge 2 -and (
            ($v.StartsWith('"') -and $v.EndsWith('"')) -or
            ($v.StartsWith("'") -and $v.EndsWith("'"))
        )) { $v = $v.Substring(1, $v.Length - 2) }
        $map[$k] = $v
    }
    return $map
}

function Get-DotEnvInt {
    param(
        [Parameter(Mandatory = $true)][hashtable]$Map,
        [Parameter(Mandatory = $true)][string]$Key,
        [Parameter(Mandatory = $true)][int]$Default
    )
    if ($Map.ContainsKey($Key) -and $Map[$Key] -match '^\d+$') {
        return [int]$Map[$Key]
    }
    return $Default
}

function Get-DotEnvStr {
    param(
        [Parameter(Mandatory = $true)][hashtable]$Map,
        [Parameter(Mandatory = $true)][string]$Key,
        [string]$Default = ""
    )
    if ($Map.ContainsKey($Key) -and $Map[$Key]) {
        return [string]$Map[$Key]
    }
    return $Default
}

function Test-GatewayRequiredByConfig {
    <#
      Whether the configured LLM chain actually goes through LiteLLM.

      LiteLLM is a dependency only while some provider in use IS "gateway". With
      LLM_DEFAULT_PROVIDER=qwen the app talks straight to the corporate OpenAI-compatible
      endpoint (QWEN_BASE_URL) and never calls :4000, so its absence must not block the
      startup — a preflight has to match the configured contract, not a fixed port list
      (030.8, 055). Empty per-tier providers inherit the default, mirroring
      LLMConfig.resolve_tier_binding.
    #>
    param([Parameter(Mandatory = $true)][hashtable]$DotEnv)

    $defaultProvider = Get-DotEnvStr -Map $DotEnv -Key "LLM_DEFAULT_PROVIDER" -Default ""
    $tierKeys = @(
        "LLM_TIER_NANO_PROVIDER",
        "LLM_TIER_SMALL_PROVIDER",
        "LLM_TIER_MID_PROVIDER",
        "LLM_TIER_FRONTIER_PROVIDER",
        "LLM_TIER_DEEP_REASONING_PROVIDER"
    )

    $providers = @($defaultProvider)
    foreach ($key in $tierKeys) {
        $value = Get-DotEnvStr -Map $DotEnv -Key $key -Default ""
        $providers += $(if ($value) { $value } else { $defaultProvider })
    }

    foreach ($provider in $providers) {
        if ($provider.Trim().ToLower() -eq "gateway") { return $true }
    }
    return $false
}

function Assert-EnvFileExists {
    if (-not (Test-Path $EnvPath)) {
        throw "ENV_FILE not found: $EnvPath. Copy from env/.env.example and fill in secrets."
    }
}

function Assert-DockerStackUp {
    param(
        [Parameter(Mandatory = $true)][hashtable]$DotEnv,
        # API стартует в этом запуске И его цепочка провайдеров идёт через LiteLLM.
        [switch]$GatewayRequired,
        # Явный отказ от gateway: продолжать, зная, что турны будут падать.
        [switch]$AllowNoGateway
    )

    if (-not (Test-CommandAvailable "docker")) {
        throw "docker not found in PATH. Install Docker Desktop."
    }

    $pgPort  = Get-DotEnvInt -Map $DotEnv -Key "POSTGRES_PUBLISH_PORT" -Default 5432
    $rdPort  = Get-DotEnvInt -Map $DotEnv -Key "REDIS_PUBLISH_PORT"    -Default 6379
    $llmPort = Get-DotEnvInt -Map $DotEnv -Key "LITELLM_PUBLISH_PORT"  -Default 4000

    $gatewayUp = Test-PortListening -Port $llmPort
    $missingDeps = @()
    if (-not (Test-PortListening -Port $pgPort)) { $missingDeps += "postgres (port $pgPort)" }
    if (-not (Test-PortListening -Port $rdPort)) { $missingDeps += "redis (port $rdPort)" }

    # LiteLLM is a hard dependency of every agent turn, and its absence is masked:
    # the LLM calls burn max_retries with backoff (~26s per agent), the turn dies at
    # the agent level, and the UI ends up showing an agent-level code (e.g.
    # `formatter_output_invalid`) as if the formatter were at fault. So fail fast with
    # an explicit opt-out, instead of a "press y" prompt that is far too easy to clear
    # without understanding the consequence (030.8, 055).
    if ($GatewayRequired -and -not $gatewayUp -and -not $AllowNoGateway) {
        Write-Host "[fail] LiteLLM не отвечает (port $llmPort) — API стартовать не будет." -ForegroundColor Red
        Write-Host ""
        Write-Host "Без gateway ни один турн не пройдёт: LLM-вызовы не доходят до модели," -ForegroundColor Yellow
        Write-Host "а пользователь увидит ошибку формата вместо реальной причины." -ForegroundColor Yellow
        Write-Host ""
        Write-Host "Вариант 1 — поднять LiteLLM в Docker:" -ForegroundColor Yellow
        Write-Host "  docker compose --env-file $EnvFile up -d postgres redis litellm" -ForegroundColor DarkYellow
        Write-Host ""
        Write-Host "Вариант 2 — ходить в корпоративный endpoint напрямую, без LiteLLM:" -ForegroundColor Yellow
        Write-Host "  в $EnvFile задайте LLM_DEFAULT_PROVIDER=`"qwen`" и LLM_TIER_*_PROVIDER=`"qwen`"," -ForegroundColor DarkYellow
        Write-Host "  а LLM_TIER_*_MODEL=`"generative-model`" (реальное имя, не алиас tier-*)." -ForegroundColor DarkYellow
        Write-Host ""
        Write-Host "Либо примите деградацию явно:" -ForegroundColor Yellow
        Write-Host "  .\scripts\dev-up.ps1 -AllowNoGateway   # API без LLM: турны будут падать" -ForegroundColor DarkYellow
        Write-Host "  .\scripts\dev-up.ps1 -SkipApi          # только MCP stubs, LLM не нужен" -ForegroundColor DarkYellow
        Write-Host ""
        throw "LiteLLM недоступен (port $llmPort); старт отменён."
    }

    if ($GatewayRequired -and -not $gatewayUp) {
        Write-Host "[warn] LiteLLM не отвечает (port $llmPort) — турны будут падать на LLM-вызовах." -ForegroundColor Yellow
    } elseif (-not $GatewayRequired -and -not $gatewayUp) {
        # Not a dependency in the configured mode: say so instead of a scary warning.
        Write-Host "[info] LiteLLM (:$llmPort) не слушает — и не нужен: LLM идёт мимо gateway." -ForegroundColor DarkGray
    }

    if ($missingDeps.Count -gt 0) {
        Write-Host "[warn] Docker-сервисы не отвечают: $($missingDeps -join ', ')" -ForegroundColor Yellow
        Write-Host "       Поднимите их:" -ForegroundColor Yellow
        Write-Host "         docker compose --env-file $EnvFile up -d postgres redis litellm" -ForegroundColor DarkYellow
        Write-Host ""
        $answer = Read-Host "Продолжить без этих сервисов? (y/N)"
        if ($answer -ne "y") { exit 1 }
    }

    if ($gatewayUp -and $missingDeps.Count -eq 0) {
        Write-Host "[ok]   Docker stack (postgres:$pgPort, redis:$rdPort, litellm:$llmPort) доступен" -ForegroundColor Green
    } elseif ($missingDeps.Count -eq 0) {
        Write-Host "[ok]   postgres:$pgPort, redis:$rdPort доступны" -ForegroundColor Green
    }

    return [pscustomobject]@{
        PostgresPort = $pgPort
        RedisPort    = $rdPort
        LiteLLMPort  = $llmPort
    }
}

function Start-DevService {
    param(
        [Parameter(Mandatory = $true)][string]$Name,
        [Parameter(Mandatory = $true)][string]$Arguments,
        [Parameter(Mandatory = $true)][int]$Port,
        [Parameter(Mandatory = $true)][string]$PoetryExe,
        [string]$HealthPath = "/docs",
        [hashtable]$Environment = @{},
        [int]$StartupTimeoutSeconds = 30
    )

    $existing = Get-PortListener -Port $Port
    if ($existing) {
        $healthUrl = "http://127.0.0.1:$Port$HealthPath"
        $alive = $false
        try {
            $r = Invoke-WebRequest -Uri $healthUrl -TimeoutSec 2 -UseBasicParsing
            $alive = ($r.StatusCode -eq 200)
        } catch {
            $alive = $false
        }

        if ($alive) {
            Write-Host "[skip] $Name — port $Port already in use (pid $($existing.pid)), healthy" -ForegroundColor Yellow
            return [pscustomobject]@{
                name     = $Name
                pid      = $existing.pid
                port     = $Port
                url      = "http://127.0.0.1:$Port"
                external = $true
            }
        }

        # Not healthy — but "not ours" and "dead" are two different things. The usual
        # foreign holder of a dev port is Docker's port publisher (com.docker.backend.exe
        # on 8080/8081 while the stubs run as containers); killing it takes down every
        # published port with it. Fail closed and tell the operator what holds the port.
        if (-not (Test-OurDevProcess -ProcessId $existing.pid)) {
            $owner = Get-ProcessOwnerName -ProcessId ([int]$existing.pid) -Table (Get-ProcessTable)
            throw ("$Name — port $Port is held by pid $($existing.pid) ($owner), which is not a " +
                "palatium-ai process. It is left alone on purpose. Stop it manually, or run " +
                ".\scripts\dev-down.ps1 -AllowForeign if you are sure.")
        }

        Write-Host "[kill] $Name — port $Port held by dead pid $($existing.pid), killing..." -ForegroundColor Yellow
        Stop-Process -Id $existing.pid -Force -ErrorAction SilentlyContinue
        Start-Sleep -Milliseconds 800

        if (Get-PortListener -Port $Port) {
            throw "$Name — port $Port still in use after kill. Try .\scripts\dev-down.ps1 -Force"
        }
    }

    $stdoutLog = Join-Path $LogDir "$Name.stdout.log"
    $stderrLog = Join-Path $LogDir "$Name.stderr.log"
    Remove-Item -Path $stdoutLog, $stderrLog -Force -ErrorAction SilentlyContinue

    $previousEnv = @{}
    foreach ($key in $Environment.Keys) {
        $previousEnv[$key] = [Environment]::GetEnvironmentVariable($key, "Process")
        [Environment]::SetEnvironmentVariable($key, [string]$Environment[$key], "Process")
    }

    try {
        $proc = Start-Process `
            -FilePath $PoetryExe `
            -ArgumentList $Arguments `
            -WorkingDirectory $RepoRoot `
            -PassThru `
            -WindowStyle Hidden `
            -RedirectStandardOutput $stdoutLog `
            -RedirectStandardError $stderrLog
    }
    finally {
        foreach ($key in $previousEnv.Keys) {
            [Environment]::SetEnvironmentVariable($key, $previousEnv[$key], "Process")
        }
    }

    $deadline = (Get-Date).AddSeconds($StartupTimeoutSeconds)
    while ((Get-Date) -lt $deadline) {
        Start-Sleep -Milliseconds 400
        if ($proc.HasExited) {
            $tail = Get-Content -Path $stderrLog -Tail 30 -ErrorAction SilentlyContinue
            throw "$Name exited early (code $($proc.ExitCode)). stderr tail:`n$($tail -join [Environment]::NewLine)"
        }
        if (Test-PortListening -Port $Port) { break }
    }

    if (-not (Test-PortListening -Port $Port)) {
        $tail = Get-Content -Path $stderrLog -Tail 30 -ErrorAction SilentlyContinue
        $msg = "$Name did not bind port $Port within ${StartupTimeoutSeconds}s.`n"
        $msg += "See $stderrLog"
        if ($tail) {
            $msg += "`n`nstderr tail:`n" + ($tail -join [Environment]::NewLine)
        }
        throw $msg
    }

    Write-Host "[ok]   $Name — pid $($proc.Id), http://127.0.0.1:$Port$HealthPath" -ForegroundColor Green
    return [pscustomobject]@{
        name     = $Name
        pid      = $proc.Id
        port     = $Port
        url      = "http://127.0.0.1:$Port"
        external = $false
    }
}

# =============================================================================
# Preflight
# =============================================================================
Assert-EnvFileExists
$PoetryExe = Get-PoetryExe
$DotEnv = Read-DotEnv -Path $EnvPath

$dockerPorts = [pscustomobject]@{
    PostgresPort = Get-DotEnvInt -Map $DotEnv -Key "POSTGRES_PUBLISH_PORT" -Default 5432
    RedisPort    = Get-DotEnvInt -Map $DotEnv -Key "REDIS_PUBLISH_PORT"    -Default 6379
    LiteLLMPort  = Get-DotEnvInt -Map $DotEnv -Key "LITELLM_PUBLISH_PORT"  -Default 4000
}

if (-not $SkipDockerCheck) {
    Write-Host ""
    Write-Host "Проверка Docker-стека..." -ForegroundColor Cyan
    # LiteLLM обязателен, только если его нет в цепочке провайдеров и мы поднимаем API.
    $gatewayRequired = (-not $SkipApi) -and (Test-GatewayRequiredByConfig -DotEnv $DotEnv)
    if (-not $gatewayRequired -and -not $SkipApi) {
        Write-Host "       LLM_DEFAULT_PROVIDER не 'gateway' — LiteLLM не требуется." -ForegroundColor DarkGray
    }
    $dockerPorts = Assert-DockerStackUp -DotEnv $DotEnv -GatewayRequired:$gatewayRequired -AllowNoGateway:$AllowNoGateway
}

# MCP токены
$McpToken = if ($env:MCP_AUTH_TOKEN -and $env:MCP_AUTH_TOKEN.Trim()) {
    $env:MCP_AUTH_TOKEN
} else { "dev-mcp-local-token" }

$McpJwt = if ($env:MCP_JWT_SECRET -and $env:MCP_JWT_SECRET.Trim()) {
    $env:MCP_JWT_SECRET
} elseif ($McpToken.Length -ge 32) {
    $McpToken
} else {
    "dev-mcp-jwt-secret-min-32-chars!!"
}

if (-not $env:MCP_AUTH_TOKEN) { $env:MCP_AUTH_TOKEN = $McpToken }
if (-not $env:MCP_JWT_SECRET) { $env:MCP_JWT_SECRET = $McpJwt }

# =============================================================================
# Общее окружение
# =============================================================================
$baseEnv = @{
    ENV_FILE         = $EnvFile
    MCP_AUTH_TOKEN   = $McpToken
    MCP_JWT_SECRET   = $McpJwt
    MCP_JWT_ISSUER   = "palatium-mcp"
    PYTHONUTF8       = "1"
    PYTHONIOENCODING = "utf-8"
}

$mcpEnv = $baseEnv.Clone()

$apiEnv = $baseEnv.Clone()
$apiEnv["POSTGRES_HOST"]          = "localhost"
$apiEnv["POSTGRES_PORT"]          = "$($dockerPorts.PostgresPort)"
$apiEnv["REDIS_HOST"]             = "localhost"
$apiEnv["REDIS_PORT"]             = "$($dockerPorts.RedisPort)"
$apiEnv["PALATIUM_GATEWAY_URL"]   = "http://127.0.0.1:$($dockerPorts.LiteLLMPort)"
# Scoped app key (scripts/litellm-provision-key.ps1); fall back to the master key
# from the env file so an unset app key can never cause a silent 401.
$apiEnv["PALATIUM_GATEWAY_KEY"]   = Get-DotEnvStr -Map $DotEnv -Key "PALATIUM_GATEWAY_KEY" `
                                        -Default (Get-DotEnvStr -Map $DotEnv -Key "LITELLM_MASTER_KEY" -Default "")
$apiEnv["MCP_HTTP_ALLOWED_HOSTS"] = "localhost,127.0.0.1,::1"
$apiEnv["APP_HOST"]               = "127.0.0.1"

# Выбор MCP_SERVERS: если gateway включён — API ходит на gateway-порты,
# иначе — напрямую на upstream stubs.
if ($WithGateway) {
    $apiEnv["MCP_SERVERS"] = '{"edms":"http://127.0.0.1:8090","analytics":"http://127.0.0.1:8091"}'
} else {
    $apiEnv["MCP_SERVERS"] = '{"edms":"http://127.0.0.1:8080","analytics":"http://127.0.0.1:8081"}'
}

# =============================================================================
# Запуск
# =============================================================================
Write-Host ""
Write-Host "palatium-ai dev stack (Poetry host profile)" -ForegroundColor Cyan
Write-Host "repo:         $RepoRoot"
Write-Host "env file:     $EnvFile"
Write-Host "postgres:     localhost:$($dockerPorts.PostgresPort) (Docker)"
Write-Host "redis:        localhost:$($dockerPorts.RedisPort) (Docker)"
Write-Host "litellm:      http://127.0.0.1:$($dockerPorts.LiteLLMPort) (Docker)"
if ($WithGateway) {
    Write-Host "mode:         gateway (API → 8090/8091 → 8080/8081)" -ForegroundColor Magenta
} else {
    Write-Host "mode:         direct (API → 8080/8081)" -ForegroundColor Cyan
}
Write-Host ""

$services = @()

# --- 1. MCP EDMS (upstream) ---
$edms = Start-DevService `
    -Name "mcp-edms" `
    -Arguments "run uvicorn mcp_servers.edms.edms_mcp_server:app --host 127.0.0.1 --port 8080" `
    -Port 8080 `
    -PoetryExe $PoetryExe `
    -HealthPath "/health" `
    -Environment $mcpEnv
$services += $edms

# --- 2. MCP Analytics (upstream) ---
$analytics = Start-DevService `
    -Name "mcp-analytics" `
    -Arguments "run uvicorn mcp_servers.analytics.analytics_mcp_server:app --host 127.0.0.1 --port 8081" `
    -Port 8081 `
    -PoetryExe $PoetryExe `
    -HealthPath "/health" `
    -Environment $mcpEnv
$services += $analytics

# --- 3. Gateway EDMS (opt-in) ---
if ($WithGateway) {
    $gwEdmsEnv = $mcpEnv.Clone()
    $gwEdmsEnv["MCP_GATEWAY_SERVER"]  = "edms"
    $gwEdmsEnv["MCP_UPSTREAM_URL"]    = "http://127.0.0.1:8080"
    $gwEdmsEnv["MCP_UPSTREAM_BEARER"] = $McpToken

    $gwEdms = Start-DevService `
        -Name "mcp-gateway-edms" `
        -Arguments "run uvicorn mcp_servers.gateway.gateway_mcp_server:app --host 127.0.0.1 --port 8090" `
        -Port 8090 `
        -PoetryExe $PoetryExe `
        -HealthPath "/health" `
        -Environment $gwEdmsEnv
    $services += $gwEdms
}

# --- 4. Gateway Analytics (opt-in) ---
if ($WithGateway) {
    $gwAnalyticsEnv = $mcpEnv.Clone()
    $gwAnalyticsEnv["MCP_GATEWAY_SERVER"]  = "analytics"
    $gwAnalyticsEnv["MCP_UPSTREAM_URL"]    = "http://127.0.0.1:8081"
    $gwAnalyticsEnv["MCP_UPSTREAM_BEARER"] = $McpToken

    $gwAnalytics = Start-DevService `
        -Name "mcp-gateway-analytics" `
        -Arguments "run uvicorn mcp_servers.gateway.gateway_mcp_server:app --host 127.0.0.1 --port 8091" `
        -Port 8091 `
        -PoetryExe $PoetryExe `
        -HealthPath "/health" `
        -Environment $gwAnalyticsEnv
    $services += $gwAnalytics
}

# --- 5. Platform stub (opt-in) ---
if ($WithPlatformStub) {
    $platform = Start-DevService `
        -Name "mcp-platform" `
        -Arguments "run uvicorn mcp_servers.platform.platform_mcp_server:app --host 127.0.0.1 --port 8082" `
        -Port 8082 `
        -PoetryExe $PoetryExe `
        -HealthPath "/health" `
        -Environment $mcpEnv
    $services += $platform
}

# --- 6. API ---
if (-not $SkipApi) {
    $app = Start-DevService `
        -Name "palatium-ai" `
        -Arguments "run python -m palatium_ai.main" `
        -Port 8000 `
        -PoetryExe $PoetryExe `
        -HealthPath "/docs" `
        -Environment $apiEnv `
        -StartupTimeoutSeconds 90
    $services += $app
} else {
    Write-Host "[skip] palatium-ai — SkipApi" -ForegroundColor Yellow
}

# =============================================================================
# Состояние
# =============================================================================
$started  = @($services | Where-Object { -not $_.external })
$existing = @($services | Where-Object { $_.external })

$state = @{
    started_at         = (Get-Date).ToString("o")
    repo_root          = $RepoRoot
    env_file           = $EnvFile
    skip_api           = [bool]$SkipApi
    with_platform_stub = [bool]$WithPlatformStub
    with_gateway       = [bool]$WithGateway
    docker_ports       = @{
        postgres = $dockerPorts.PostgresPort
        redis    = $dockerPorts.RedisPort
        litellm  = $dockerPorts.LiteLLMPort
    }
    services           = $services
}
$state | ConvertTo-Json -Depth 5 | Set-Content -Path $StateFile -Encoding UTF8

Write-Host ""
if ($started.Count -eq 0 -and $existing.Count -eq $services.Count) {
    Write-Host "Все запрошенные сервисы уже запущены (внешние процессы)." -ForegroundColor Green
} elseif ($started.Count -gt 0) {
    Write-Host "Запущено: $($started.Count) новых, $($existing.Count) уже работали." -ForegroundColor Green
}

Write-Host ""
Write-Host "Ready:" -ForegroundColor Cyan
if (-not $SkipApi) {
    Write-Host "  API swagger:       http://127.0.0.1:8000/docs"
    Write-Host "  API health:        http://127.0.0.1:8000/health"
}
Write-Host "  EDMS MCP:          http://127.0.0.1:8080/health"
Write-Host "  Analytics MCP:     http://127.0.0.1:8081/health"
if ($WithGateway) {
    Write-Host "  Gateway EDMS:      http://127.0.0.1:8090/health" -ForegroundColor Magenta
    Write-Host "  Gateway Analytics: http://127.0.0.1:8091/health" -ForegroundColor Magenta
}
if ($WithPlatformStub) {
    Write-Host "  Platform stub:     http://127.0.0.1:8082/health (optional discovery-only)"
}
Write-Host "  LiteLLM:           http://127.0.0.1:$($dockerPorts.LiteLLMPort)/health/liveliness"
Write-Host ""

if ($WithGateway) {
    Write-Host "Mode: gateway — API обращается к MCP через проксирование." -ForegroundColor Magenta
    Write-Host "      Проверка политик (pin_allowlist / pin_filter / upstream_policy)." -ForegroundColor DarkGray
} else {
    Write-Host "Mode: direct — API обращается к MCP stubs напрямую." -ForegroundColor Cyan
}
Write-Host ""
Write-Host "Smoke auth:  poetry run python scripts/smoke_mcp_auth.py --skip-api"
Write-Host ""
Write-Host "Logs:   $LogDir"
Write-Host "State:  $StateFile"
Write-Host ""
Write-Host "Остановить:  .\scripts\dev-down.ps1" -ForegroundColor DarkGray
Write-Host ""
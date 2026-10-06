#Requires -Version 5.1
<#
.SYNOPSIS
  Stop palatium-ai app and all local MCP server stubs (Poetry host profile).

.DESCRIPTION
  Останавливает процессы на портах локального dev-стека:
    - palatium-ai API         8000
    - Gateway Analytics       8091 (опционально)
    - Gateway EDMS            8090 (опционально)
    - Platform MCP stub       8082 (опционально)
    - Analytics MCP stub      8081
    - EDMS MCP stub           8080

  Порядок остановки: gateway → upstream. Сначала снимаем прокси,
  потом upstream, чтобы не оставить висящих соединений.

  Docker-сервисы (Postgres/Redis/Neo4j/LiteLLM) НЕ трогаются —
  для них используйте: docker compose --env-file env/.env down

  ⚠ Dev-порты пересекаются с опубликованными портами контейнеров: пока MCP-стабы
  подняты как контейнеры, на 8080/8081 слушает Docker Desktop
  (com.docker.backend.exe). Поэтому «на порту что-то есть» НЕ значит «это наше»:
  скрипт останавливает только процессы, запущенные из этого репозитория
  (python -m palatium_ai.main / uvicorn mcp_servers...), а чужой слушатель
  пропускает с пометкой. Убийство docker-прокси уносит с собой ВСЕ опубликованные
  порты (postgres/redis/litellm/neo4j) и требует перезапуска Docker Desktop.
  Осознанно убить чужое — только явным -AllowForeign.

  Использует scripts/.dev/processes.json для имён сервисов.
  Слушатели портов пересканируются — вручную запущенные процессы
  (наши, из этого репо) тоже будут остановлены.

  uvicorn --reload spawns child workers; скрипт останавливает дерево
  процессов и повторяет до освобождения порта.

  Pair with scripts/dev-up.ps1.
#>

[CmdletBinding()]
param(
    [switch]$Force,
    # Escape hatch: stop whatever holds a dev port, even a foreign process. Off by
    # default because the usual foreign owner here is Docker's port publisher (020).
    [switch]$AllowForeign
)

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

# Ownership rule for the dev ports. Shared with dev-up.ps1 so the two scripts cannot
# drift apart on what counts as "our" process — see the file header.
. (Join-Path $PSScriptRoot "lib/dev-common.ps1")

$DevDir    = Join-Path $PSScriptRoot ".dev"
$StateFile = Join-Path $DevDir "processes.json"

$DevPorts = @(
    @{ Name = "palatium-ai";           Port = 8000 },
    @{ Name = "mcp-gateway-analytics"; Port = 8091 },
    @{ Name = "mcp-gateway-edms";      Port = 8090 },
    @{ Name = "mcp-platform";          Port = 8082 },
    @{ Name = "mcp-analytics";         Port = 8081 },
    @{ Name = "mcp-edms";              Port = 8080 }
)

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

function Get-ChildProcessIds {
    param([Parameter(Mandatory = $true)][int]$ProcessId)
    Get-CimInstance Win32_Process -Filter "ParentProcessId=$ProcessId" -ErrorAction SilentlyContinue |
        ForEach-Object { [int]$_.ProcessId }
}

function Stop-ProcessTree {
    param(
        [Parameter(Mandatory = $true)][int]$ProcessId,
        [switch]$UseForce
    )
    foreach ($childId in (Get-ChildProcessIds -ProcessId $ProcessId)) {
        Stop-ProcessTree -ProcessId $childId -UseForce:$UseForce
    }
    $proc = Get-Process -Id $ProcessId -ErrorAction SilentlyContinue
    if (-not $proc) { return }
    if ($UseForce) {
        Stop-Process -Id $ProcessId -Force -ErrorAction SilentlyContinue
    } else {
        Stop-Process -Id $ProcessId -ErrorAction SilentlyContinue
    }
}

function Stop-PortService {
    param(
        [Parameter(Mandatory = $true)][string]$Name,
        [Parameter(Mandatory = $true)][int]$Port,
        [Parameter(Mandatory = $true)][hashtable]$Table,
        [switch]$Force,
        [switch]$AllowForeign
    )

    $maxAttempts = 8
    $hadListener = $false

    for ($attempt = 1; $attempt -le $maxAttempts; $attempt++) {
        $listener = Get-PortListener -Port $Port
        if (-not $listener) {
            if (-not $hadListener) {
                Write-Host "[skip] $Name — not running (port $Port free)" -ForegroundColor DarkGray
            } else {
                Write-Host "[ok]   $Name — stopped" -ForegroundColor Green
            }
            return $true
        }

        # Ownership gate before anything is stopped: a shared port is not proof of
        # ownership, and a mis-kill here is not recoverable by re-running dev-up.
        if (-not $AllowForeign -and -not (Test-OurDevProcess -ProcessId $listener.pid -Table $Table)) {
            $owner = Get-ProcessOwnerName -ProcessId ([int]$listener.pid) -Table $Table
            Write-Host "[skip] $Name — port $Port is held by pid $($listener.pid) ($owner), not a repo process" -ForegroundColor Yellow
            Write-Host "       left running on purpose; stop it manually, or re-run with -AllowForeign" -ForegroundColor DarkGray
            return $true
        }

        $hadListener = $true
        $useForce = $Force.IsPresent -or $attempt -ge 2
        $suffix = if ($attempt -gt 1) { " (attempt $attempt)" } else { "" }

        Write-Host "[stop] $Name — pid $($listener.pid), port $Port$suffix" -ForegroundColor Cyan
        Stop-ProcessTree -ProcessId $listener.pid -UseForce:$useForce
        Start-Sleep -Milliseconds 400
    }

    if (Test-PortListening -Port $Port) {
        $remaining = Get-PortListener -Port $Port
        Write-Host "[warn] $Name — port $Port still in use (pid $($remaining.pid)). Try -Force." -ForegroundColor Yellow
        return $false
    }

    Write-Host "[ok]   $Name — stopped" -ForegroundColor Green
    return $true
}

# =============================================================================
# Читаем известные имена из state
# =============================================================================
$knownNames = @{}
if (Test-Path $StateFile) {
    $state = Get-Content -Path $StateFile -Raw -Encoding UTF8 | ConvertFrom-Json
    foreach ($svc in $state.services) {
        $knownNames[[int]$svc.port] = [string]$svc.name
    }
}

Write-Host ""
Write-Host "palatium-ai dev stack — shutdown" -ForegroundColor Cyan
Write-Host ""

$anyListening = $false
foreach ($entry in $DevPorts) {
    if (Test-PortListening -Port $entry.Port) {
        $anyListening = $true
        break
    }
}

if (-not $anyListening) {
    Write-Host "Нет активных dev-сервисов на портах 8000, 8080, 8081, 8082, 8090, 8091." -ForegroundColor Green
    if (Test-Path $StateFile) { Remove-Item -Path $StateFile -Force }
    Write-Host ""
    Write-Host "Docker-стек не тронут — для остановки используйте:" -ForegroundColor DarkGray
    Write-Host "  docker compose --env-file env/.env down" -ForegroundColor DarkGray
    Write-Host ""
    exit 0
}

$failed = $false
$skippedForeign = @()
# One snapshot for all six ports: the ownership walk inspects ancestors, which must not
# shift under it between checks.
$processTable = Get-ProcessTable
foreach ($entry in $DevPorts) {
    $name = if ($knownNames.ContainsKey($entry.Port)) {
        $knownNames[$entry.Port]
    } else {
        $entry.Name
    }
    $listener = Get-PortListener -Port $entry.Port
    if ($listener -and -not $AllowForeign -and -not (Test-OurDevProcess -ProcessId $listener.pid -Table $processTable)) {
        $skippedForeign += "$name (:$($entry.Port), pid $($listener.pid))"
    }
    $ok = Stop-PortService -Name $name -Port $entry.Port -Table $processTable -Force:$Force -AllowForeign:$AllowForeign
    if (-not $ok) { $failed = $true }
}

if (Test-Path $StateFile) { Remove-Item -Path $StateFile -Force }

Write-Host ""
if ($skippedForeign.Count -gt 0) {
    Write-Host "Оставлены чужие процессы на dev-портах: $($skippedForeign -join ', ')" -ForegroundColor Yellow
    Write-Host "Это не наши сервисы (обычно порт-прокси Docker). Остановить их можно вручную" -ForegroundColor DarkGray
    Write-Host "или повторным запуском с -AllowForeign — но это уронит и Docker-стек." -ForegroundColor DarkGray
    Write-Host ""
}
if ($failed) {
    Write-Host "Некоторые сервисы могут ещё работать. Попробуйте -Force." -ForegroundColor Yellow
    exit 1
}

Write-Host "Dev stack stopped." -ForegroundColor Green
Write-Host ""
Write-Host "Docker-сервисы (Postgres/Redis/Neo4j/LiteLLM) не тронуты." -ForegroundColor DarkGray
Write-Host "Остановить их:  docker compose --env-file env/.env down" -ForegroundColor DarkGray
Write-Host ""
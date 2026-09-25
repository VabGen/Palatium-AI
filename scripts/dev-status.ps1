#Requires -Version 5.1
<#
.SYNOPSIS
  Status of palatium-ai dev stack (host Poetry processes + Docker services).

.DESCRIPTION
  Показывает:
    • host-процессы (MCP stubs + gateway + API), запущенные через dev-up.ps1
    • Docker-сервисы (Postgres, Redis, Neo4j, LiteLLM)
    • список моделей LiteLLM (tier-*)

.PARAMETER EnvFile
  Какой env-файл использовать. По умолчанию env/.env.
#>

[CmdletBinding()]
param(
    [string]$EnvFile = "env/.env"
)

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

$RepoRoot = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
$EnvPath  = Join-Path $RepoRoot $EnvFile

# -----------------------------------------------------------------------------
# Хелперы
# -----------------------------------------------------------------------------
function Get-PortOwnerPid {
    param([Parameter(Mandatory = $true)][int]$Port)
    $conn = Get-NetTCPConnection -LocalPort $Port -State Listen -ErrorAction SilentlyContinue |
        Select-Object -First 1
    if (-not $conn) { return $null }
    return [int]$conn.OwningProcess
}

function Test-UrlOk {
    param([Parameter(Mandatory = $true)][string]$Url)
    try {
        $r = Invoke-WebRequest -Uri $Url -TimeoutSec 2 -UseBasicParsing
        return $r.StatusCode -eq 200
    } catch {
        return $false
    }
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

# -----------------------------------------------------------------------------
# Данные из .env
# -----------------------------------------------------------------------------
$DotEnv = Read-DotEnv -Path $EnvPath

$pgPort   = Get-DotEnvInt -Map $DotEnv -Key "POSTGRES_PUBLISH_PORT" -Default 5432
$rdPort   = Get-DotEnvInt -Map $DotEnv -Key "REDIS_PUBLISH_PORT"    -Default 6379
$neoPort  = Get-DotEnvInt -Map $DotEnv -Key "NEO4J_HTTP_PORT"       -Default 7474
$boltPort = Get-DotEnvInt -Map $DotEnv -Key "NEO4J_BOLT_PORT"       -Default 7687
$llmPort  = Get-DotEnvInt -Map $DotEnv -Key "LITELLM_PUBLISH_PORT"  -Default 4000
$apiPort  = Get-DotEnvInt -Map $DotEnv -Key "API_PUBLISH_PORT"      -Default 8000

$masterKey = Get-DotEnvStr -Map $DotEnv -Key "LITELLM_MASTER_KEY" -Default "sk-palatium-master"

# -----------------------------------------------------------------------------
# Вывод
# -----------------------------------------------------------------------------
Write-Host ""
Write-Host "=== palatium-ai dev stack status ===" -ForegroundColor Cyan
Write-Host "env file: $EnvFile"
Write-Host ""

Write-Host "Host-процессы (Poetry):" -ForegroundColor Yellow
$hostServices = @(
    @{ Name = "palatium-ai API";       Port = $apiPort; Url = "http://127.0.0.1:$apiPort/health" },
    @{ Name = "Gateway Analytics";     Port = 8091;     Url = "http://127.0.0.1:8091/health" },
    @{ Name = "Gateway EDMS";          Port = 8090;     Url = "http://127.0.0.1:8090/health" },
    @{ Name = "Platform MCP stub";     Port = 8082;     Url = "http://127.0.0.1:8082/health" },
    @{ Name = "Analytics MCP stub";    Port = 8081;     Url = "http://127.0.0.1:8081/health" },
    @{ Name = "EDMS MCP stub";         Port = 8080;     Url = "http://127.0.0.1:8080/health" }
)
foreach ($svc in $hostServices) {
    $ownerPid = Get-PortOwnerPid -Port $svc.Port
    if ($ownerPid) {
        $healthy = Test-UrlOk -Url $svc.Url
        $status  = if ($healthy) { "healthy" } else { "listening (no /health)" }
        $color   = if ($healthy) { "Green" } else { "Yellow" }
        Write-Host ("  {0,-22} :{1,-5}  pid={2,-7}  {3}" -f $svc.Name, $svc.Port, $ownerPid, $status) -ForegroundColor $color
    } else {
        Write-Host ("  {0,-22} :{1,-5}  —" -f $svc.Name, $svc.Port) -ForegroundColor DarkGray
    }
}

Write-Host ""
Write-Host "Docker-сервисы:" -ForegroundColor Yellow
$dockerServices = @(
    @{ Name = "Postgres";    Port = $pgPort },
    @{ Name = "Redis";       Port = $rdPort },
    @{ Name = "Neo4j HTTP";  Port = $neoPort },
    @{ Name = "Neo4j Bolt";  Port = $boltPort },
    @{ Name = "LiteLLM";     Port = $llmPort }
)
foreach ($svc in $dockerServices) {
    $ownerPid = Get-PortOwnerPid -Port $svc.Port
    if ($ownerPid) {
        Write-Host ("  {0,-14} :{1,-5}  OK" -f $svc.Name, $svc.Port) -ForegroundColor Green
    } else {
        Write-Host ("  {0,-14} :{1,-5}  --" -f $svc.Name, $svc.Port) -ForegroundColor Red
    }
}

Write-Host ""
Write-Host "LiteLLM модели:" -ForegroundColor Yellow
try {
    $r = Invoke-RestMethod `
        -Uri "http://127.0.0.1:$llmPort/v1/models" `
        -Headers @{ Authorization = "Bearer $masterKey" } `
        -TimeoutSec 3
    if ($r.data) {
        foreach ($m in $r.data) {
            Write-Host "  • $($m.id)" -ForegroundColor Green
        }
    } else {
        Write-Host "  (пусто)" -ForegroundColor DarkGray
    }
} catch {
    Write-Host "  LiteLLM недоступен: $($_.Exception.Message)" -ForegroundColor Red
}

Write-Host ""
Write-Host "Health endpoints:" -ForegroundColor Yellow
$endpoints = @(
    @{ Name = "API /health";         Url = "http://127.0.0.1:$apiPort/health" },
    @{ Name = "API /docs";           Url = "http://127.0.0.1:$apiPort/docs" },
    @{ Name = "LiteLLM liveliness";  Url = "http://127.0.0.1:$llmPort/health/liveliness" },
    @{ Name = "MCP EDMS";            Url = "http://127.0.0.1:8080/health" },
    @{ Name = "MCP Analytics";       Url = "http://127.0.0.1:8081/health" },
    @{ Name = "Gateway EDMS";        Url = "http://127.0.0.1:8090/health" },
    @{ Name = "Gateway Analytics";   Url = "http://127.0.0.1:8091/health" }
)
foreach ($ep in $endpoints) {
    if (Test-UrlOk -Url $ep.Url) {
        Write-Host ("  {0,-24} {1}" -f $ep.Name, $ep.Url) -ForegroundColor Green
    } else {
        Write-Host ("  {0,-24} {1}  [no response]" -f $ep.Name, $ep.Url) -ForegroundColor DarkGray
    }
}

Write-Host ""
Write-Host "State (dev-up): scripts/.dev/processes.json" -ForegroundColor DarkGray
Write-Host ""
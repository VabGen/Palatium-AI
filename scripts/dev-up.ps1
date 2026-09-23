#Requires -Version 5.1
<#
.SYNOPSIS
  Start palatium-ai app and remote MCP stubs for development.

.DESCRIPTION
  Launches:
    - EDMS MCP stub       http://127.0.0.1:8080
    - Analytics MCP stub  http://127.0.0.1:8081
    - palatium-ai API     http://127.0.0.1:8000 (from env/.env)

  Platform tools are Host-local (pins + PlatformToolHandler) — no :8082 by default.
  Optional: -WithPlatformStub for external discovery-only smoke of mcp_servers/platform.

  Process IDs and logs are stored under scripts/.dev/ for manual cleanup.
  Stop the stack with scripts/dev-down.ps1.

.PARAMETER SkipApi
  Start only MCP stubs (skip palatium-ai on :8000).

.PARAMETER WithPlatformStub
  Also start optional platform stub on :8082 (discovery-only; Host never executes via it).

  .\scripts\dev-down.ps1 -Force   # полная остановка
  .\scripts\dev-up.ps1            # чистый старт
#>

param(
    [switch]$SkipApi,
    [switch]$WithPlatformStub
)

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

$RepoRoot = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
$DevDir = Join-Path $PSScriptRoot ".dev"
$LogDir = Join-Path $DevDir "logs"
$StateFile = Join-Path $DevDir "processes.json"

New-Item -ItemType Directory -Force -Path $LogDir | Out-Null

function Test-CommandAvailable {
    param([Parameter(Mandatory = $true)][string]$Name)
    return [bool](Get-Command $Name -ErrorAction SilentlyContinue)
}

function Get-PortListener {
    param([Parameter(Mandatory = $true)][int]$Port)

    $conn = Get-NetTCPConnection -LocalPort $Port -State Listen -ErrorAction SilentlyContinue |
        Select-Object -First 1
    if (-not $conn) {
        return $null
    }

    return [pscustomobject]@{
        pid  = [int]$conn.OwningProcess
        port = $Port
    }
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

function Start-DevService {
    param(
        [Parameter(Mandatory = $true)][string]$Name,
        [Parameter(Mandatory = $true)][string]$Arguments,
        [Parameter(Mandatory = $true)][int]$Port,
        [string]$HealthPath = "/docs",
        [hashtable]$Environment = @{},
        [int]$StartupTimeoutSeconds = 20
    )

    $existing = Get-PortListener -Port $Port
    if ($existing) {
        Write-Host "[skip] $Name - port $Port already in use (pid $($existing.pid))" -ForegroundColor Yellow
        if ($Name -eq "mcp-platform") {
            Write-Host "       Stale platform stub? Run scripts/dev-down.ps1 -Force, then dev-up again." -ForegroundColor DarkYellow
        }
        return [pscustomobject]@{
            name     = $Name
            pid      = $existing.pid
            port     = $Port
            url      = "http://127.0.0.1:$Port"
            external = $true
        }
    }

    $stdoutLog = Join-Path $LogDir "$Name.stdout.log"
    $stderrLog = Join-Path $LogDir "$Name.stderr.log"

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
            $tail = Get-Content -Path $stderrLog -Tail 20 -ErrorAction SilentlyContinue
            throw "$Name exited early (code $($proc.ExitCode)). stderr tail:`n$($tail -join [Environment]::NewLine)"
        }
        if (Test-PortListening -Port $Port) {
            break
        }
    }

    if (-not (Test-PortListening -Port $Port)) {
        throw "$Name did not bind port $Port within ${StartupTimeoutSeconds}s. See $stderrLog"
    }

    Write-Host "[ok]   $Name - pid $($proc.Id), http://127.0.0.1:$Port$HealthPath" -ForegroundColor Green
    return [pscustomobject]@{
        name     = $Name
        pid      = $proc.Id
        port     = $Port
        url      = "http://127.0.0.1:$Port"
        external = $false
    }
}

$PoetryExe = Get-PoetryExe
$McpToken = if ($env:MCP_AUTH_TOKEN) { $env:MCP_AUTH_TOKEN } else { "dev-mcp-local-token" }
$McpJwt = if ($env:MCP_JWT_SECRET) {
    $env:MCP_JWT_SECRET
} elseif ($McpToken.Length -ge 32) {
    $McpToken
} else {
    "dev-mcp-jwt-secret-min-32-chars!!"
}
# mcp_servers (stub runtime) + src (domain schema SoT — Phase 4)
$McpPythonPath = @(
    (Join-Path $RepoRoot "mcp_servers"),
    (Join-Path $RepoRoot "src")
) -join [IO.Path]::PathSeparator
if (-not $env:MCP_AUTH_TOKEN) {
    $env:MCP_AUTH_TOKEN = $McpToken
    Write-Host "MCP_AUTH_TOKEN not set; using dev-mcp-local-token for stubs + API process env" -ForegroundColor Yellow
}
if (-not $env:MCP_JWT_SECRET) {
    $env:MCP_JWT_SECRET = $McpJwt
}

Write-Host ""
Write-Host "palatium-ai dev stack" -ForegroundColor Cyan
Write-Host "repo: $RepoRoot"
Write-Host ""

$services = @()

$mcpEnv = @{
    MCP_AUTH_TOKEN = $McpToken
    MCP_JWT_SECRET = $McpJwt
    MCP_JWT_ISSUER = "palatium-mcp"
    PYTHONPATH     = $McpPythonPath
    PYTHONUTF8     = "1"
    PYTHONIOENCODING = "utf-8"
}

$apiEnv = @{
    MCP_AUTH_TOKEN = $McpToken
    MCP_JWT_SECRET = $McpJwt
    MCP_JWT_ISSUER = "palatium-mcp"
    PYTHONUTF8     = "1"
    PYTHONIOENCODING = "utf-8"
}

$edms = Start-DevService `
    -Name "mcp-edms" `
    -Arguments "run uvicorn edms_mcp_server:app --app-dir mcp_servers/edms --host 127.0.0.1 --port 8080" `
    -Port 8080 `
    -HealthPath "/health" `
    -Environment $mcpEnv
$services += $edms

$analytics = Start-DevService `
    -Name "mcp-analytics" `
    -Arguments "run uvicorn analytics_mcp_server:app --app-dir mcp_servers/analytics --host 127.0.0.1 --port 8081" `
    -Port 8081 `
    -HealthPath "/health" `
    -Environment $mcpEnv
$services += $analytics

if ($WithPlatformStub) {
    $platform = Start-DevService `
        -Name "mcp-platform" `
        -Arguments "run uvicorn platform_mcp_server:app --app-dir mcp_servers/platform --host 127.0.0.1 --port 8082" `
        -Port 8082 `
        -HealthPath "/health" `
        -Environment $mcpEnv
    $services += $platform
}

if (-not $SkipApi) {
    $app = Start-DevService `
        -Name "palatium-ai" `
        -Arguments "run python -m palatium_ai.main" `
        -Port 8000 `
        -HealthPath "/docs" `
        -Environment $apiEnv `
        -StartupTimeoutSeconds 90
    $services += $app
} else {
    Write-Host "[skip] palatium-ai - SkipApi" -ForegroundColor Yellow
}

$started = @($services | Where-Object { -not $_.external })
$existing = @($services | Where-Object { $_.external })

$state = @{
    started_at = (Get-Date).ToString("o")
    repo_root  = $RepoRoot
    skip_api   = [bool]$SkipApi
    with_platform_stub = [bool]$WithPlatformStub
    services   = $services
}
$state | ConvertTo-Json -Depth 4 | Set-Content -Path $StateFile -Encoding UTF8

Write-Host ""
if ($started.Count -eq 0 -and $existing.Count -eq $services.Count) {
    Write-Host "All requested dev services already running." -ForegroundColor Green
} elseif ($started.Count -gt 0) {
    Write-Host "Started $($started.Count) service(s), $($existing.Count) already running." -ForegroundColor Green
}
Write-Host ""
Write-Host "Ready:" -ForegroundColor Cyan
if (-not $SkipApi) {
    Write-Host "  API swagger:   http://127.0.0.1:8000/docs"
}
Write-Host "  EDMS MCP:      http://127.0.0.1:8080/health"
Write-Host "  Analytics MCP: http://127.0.0.1:8081/health"
Write-Host "  Platform:      Host-local (no :8082)"
if ($WithPlatformStub) {
    Write-Host "  Platform stub: http://127.0.0.1:8082/health (optional discovery-only)"
}
Write-Host "  Smoke auth:    poetry run python scripts/smoke_mcp_auth.py --skip-api"
Write-Host ""
Write-Host "Logs:  $LogDir"
Write-Host "State: $StateFile"
Write-Host ""
if ($started.Count -gt 0) {
    Write-Host "Stop processes started by this script:" -ForegroundColor DarkGray
    foreach ($svc in $started) {
        Write-Host "  Stop-Process -Id $($svc.pid)  # $($svc.name)" -ForegroundColor DarkGray
    }
    Write-Host ""
}
if ($existing.Count -gt 0) {
    Write-Host "Already running (started outside dev-up):" -ForegroundColor DarkGray
    foreach ($svc in $existing) {
        Write-Host "  pid $($svc.pid) on port $($svc.port)  # $($svc.name)" -ForegroundColor DarkGray
    }
    Write-Host ""
}

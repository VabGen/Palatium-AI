#Requires -Version 5.1
<#
.SYNOPSIS
  Stop palatium-ai app and all local MCP server stubs.

.DESCRIPTION
  Stops processes listening on dev stack ports:
    - palatium-ai API     8000
    - Analytics MCP stub  8081
    - EDMS MCP stub       8080

  Uses scripts/.dev/processes.json for service names when available;
  port listeners are always rescanned so manually started processes are included.

  uvicorn --reload spawns child workers; this script stops the full process tree
  and retries until each port is free.

  Pair with scripts/dev-up.ps1.
#>

[CmdletBinding()]
param(
    [switch]$Force
)

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

$DevDir = Join-Path $PSScriptRoot ".dev"
$StateFile = Join-Path $DevDir "processes.json"

$DevPorts = @(
    @{ Name = "palatium-ai"; Port = 8000 },
    @{ Name = "mcp-analytics"; Port = 8081 },
    @{ Name = "mcp-edms"; Port = 8080 }
)

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
    if (-not $proc) {
        return
    }

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
        [switch]$Force
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
    Write-Host "No dev services listening on ports 8000, 8080, 8081." -ForegroundColor Green
    if (Test-Path $StateFile) {
        Remove-Item -Path $StateFile -Force
    }
    Write-Host ""
    exit 0
}

$failed = $false
foreach ($entry in $DevPorts) {
    $name = if ($knownNames.ContainsKey($entry.Port)) {
        $knownNames[$entry.Port]
    } else {
        $entry.Name
    }

    $ok = Stop-PortService -Name $name -Port $entry.Port -Force:$Force
    if (-not $ok) {
        $failed = $true
    }
}

if (Test-Path $StateFile) {
    Remove-Item -Path $StateFile -Force
}

Write-Host ""
if ($failed) {
    Write-Host "Some services may still be running. Re-run with -Force if needed." -ForegroundColor Yellow
    exit 1
}

Write-Host "Dev stack stopped." -ForegroundColor Green
Write-Host ""

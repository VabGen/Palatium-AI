#Requires -Version 5.1
<#
.SYNOPSIS
  Run mypy for both: src/palatium_ai (main) and mcp_servers/ (stubs).

.DESCRIPTION
  Wrapper for two mypy invocations with separate configs:
    • pyproject.toml → [tool.mypy]           — src/palatium_ai
    • mcp_servers/mypy.ini                    — mcp_servers/

  Падает с тем же exit code, что вернул mypy. Не переопределяет
  ErrorActionPreference — mypy exit 1 не считается исключением.

.EXAMPLE
  .\scripts\type-check.ps1              # обе проверки
  .\scripts\type-check.ps1 -MainOnly    # только src/palatium_ai
  .\scripts\type-check.ps1 -McpOnly     # только mcp_servers
#>

[CmdletBinding()]
param(
    [switch]$MainOnly,
    [switch]$McpOnly
)

$Root = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
Set-Location $Root

$failed = 0

if (-not $McpOnly) {
    Write-Host "[1/2] mypy: src/palatium_ai (main)" -ForegroundColor Cyan
    poetry run mypy .
    if ($LASTEXITCODE -ne 0) { $failed = 1 }
}

if (-not $MainOnly) {
    Write-Host ""
    Write-Host "[2/2] mypy: mcp_servers" -ForegroundColor Cyan
    poetry run mypy --config-file mcp_servers/mypy.ini mcp_servers
    if ($LASTEXITCODE -ne 0) { $failed = 1 }
}

if ($failed -eq 0) {
    Write-Host ""
    Write-Host "OK — все проверки прошли." -ForegroundColor Green
} else {
    Write-Host ""
    Write-Host "FAIL — см. вывод выше." -ForegroundColor Red
}

exit $failed
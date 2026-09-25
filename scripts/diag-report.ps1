#Requires -Version 5.1
<#
.SYNOPSIS
  Диагностический отчёт по стеку palatium-ai (Docker + host + конфиги).

.DESCRIPTION
  Собирает в один файл всё, что нужно для разбора рассинхрона:
    • версии Docker / Compose
    • контейнеры (с профилями docker-mcp + docker-api), сети, volumes, образы
    • занятость портов проекта
    • логи api / mcp-edms / mcp-analytics / litellm
    • секции [tool.poetry] и dockerfile: из compose-файлов

  ПЕРЕД записью в файл вывод прогоняется через redaction
  (Bearer/sk-*/password/api_key/secret/token/PEM) — см. правило 020.

.PARAMETER EnvFile
  Какой env-файл использовать. По умолчанию env/.env.

.PARAMETER OutFile
  Куда писать отчёт. По умолчанию diag-report.txt в корне репозитория
  (файл в .gitignore, коммитить не нужно).

.PARAMETER Tail
  Сколько последних строк логов брать. По умолчанию 50.

.EXAMPLE
  .\scripts\diag-report.ps1

.EXAMPLE
  .\scripts\diag-report.ps1 -EnvFile env/.env.dev -Tail 200 -OutFile C:\temp\diag.txt
#>

[CmdletBinding()]
param(
    [string]$EnvFile = "env/.env",
    [string]$OutFile = "diag-report.txt",
    [int]$Tail = 50
)

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

$RepoRoot = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
$EnvPath  = Join-Path $RepoRoot $EnvFile
$OutPath  = if ([System.IO.Path]::IsPathRooted($OutFile)) { $OutFile } else { Join-Path $RepoRoot $OutFile }

$Profiles = @("--profile", "docker-mcp", "--profile", "docker-api")

# -----------------------------------------------------------------------------
# Redaction (020: секреты не должны попадать в артефакт)
# -----------------------------------------------------------------------------
# $1 сохраняет префикс ("Bearer ", "API_KEY="), значение заменяется на <redacted>
$Redactions = @(
    @{ Pattern = 'sk-[A-Za-z0-9_\-]{6,}'; Replacement = '<redacted>' }
    @{ Pattern = '(?i)(authorization:\s*bearer\s+)\S+'; Replacement = '$1<redacted>' }
    @{ Pattern = '(?i)(bearer\s+)[A-Za-z0-9._\-]{8,}'; Replacement = '$1<redacted>' }
    @{ Pattern = '(?i)((?:password|passwd|api[_-]?key|secret|token)[a-z_]*\s*[=:]\s*)["'']?[^\s"'',]+'; Replacement = '$1<redacted>' }
    @{ Pattern = '(?s)-----BEGIN [A-Z ]+-----.*?-----END [A-Z ]+-----'; Replacement = '<redacted>' }
)

function Protect-Secrets {
    param([Parameter(Mandatory = $true)][AllowEmptyString()][string]$Text)
    if (-not $Text) { return $Text }
    $redacted = $Text
    foreach ($rule in $Redactions) {
        $redacted = $redacted -replace $rule.Pattern, $rule.Replacement
    }
    return $redacted
}

# -----------------------------------------------------------------------------
# Сборка отчёта
# -----------------------------------------------------------------------------
$sb = [System.Text.StringBuilder]::new()

function Add-Section {
    param(
        [Parameter(Mandatory = $true)][string]$Title,
        [Parameter(Mandatory = $true)][scriptblock]$Body
    )
    [void]$sb.AppendLine("=== $Title ===")
    try {
        $out = (& $Body 2>&1 | Out-String -Width 200)
        if ([string]::IsNullOrWhiteSpace($out)) { [void]$sb.AppendLine("(no output)") }
        else { [void]$sb.AppendLine($out.TrimEnd()) }
    } catch {
        [void]$sb.AppendLine("(error: $($_.Exception.Message))")
    }
    [void]$sb.AppendLine("")
}

[void]$sb.AppendLine("Palatium-AI diagnostics")
[void]$sb.AppendLine("Generated: $(Get-Date -Format 'yyyy-MM-dd HH:mm:ss K')")
[void]$sb.AppendLine("RepoRoot:  $RepoRoot")
[void]$sb.AppendLine("EnvFile:   $EnvFile (exists: $(Test-Path -LiteralPath $EnvPath))")
[void]$sb.AppendLine("")

Add-Section -Title "System" -Body {
    docker --version
    docker compose version
    "PowerShell: $($PSVersionTable.PSVersion)"
}

# --env-file добавляем только если файл реально есть
$composeArgs = @()
if (Test-Path -LiteralPath $EnvPath) { $composeArgs = @("--env-file", $EnvPath) }

Add-Section -Title "Containers (with profiles)" -Body {
    docker compose @composeArgs @Profiles ps
}

Add-Section -Title "Containers (no --profile; shows what is actually running)" -Body {
    docker compose @composeArgs ps
}

Add-Section -Title "Networks" -Body { docker network ls }

Add-Section -Title "Volumes"      -Body { docker volume ls }

Add-Section -Title "Images"       -Body { docker images | Select-String -Pattern "palatium" }

Add-Section -Title "Ports" -Body {
    @(8000, 8080, 8081, 8082, 8090, 8091, 4000, 5432, 6379, 7474, 7687) | ForEach-Object {
        $conn = Get-NetTCPConnection -LocalPort $_ -State Listen -ErrorAction SilentlyContinue |
            Select-Object -First 1
        if ($conn) { "  :{0,-5} pid={1}" -f $_, $conn.OwningProcess }
        else       { "  :{0,-5} -" -f $_ }
    }
}

Add-Section -Title "Api logs"         -Body { docker compose @composeArgs @Profiles logs api --tail $Tail }
Add-Section -Title "mcp-edms logs"    -Body { docker compose @composeArgs @Profiles logs mcp-edms --tail $Tail }
Add-Section -Title "mcp-analytics logs" -Body { docker compose @composeArgs @Profiles logs mcp-analytics --tail $Tail }
Add-Section -Title "litellm logs"     -Body { docker compose @composeArgs logs litellm --tail $Tail }

Add-Section -Title "pyproject.toml [tool.poetry]" -Body {
    (Select-String -Path (Join-Path $RepoRoot "pyproject.toml") -Pattern "\[tool\.poetry\]" -Context 0,10).Context.PostContext -join "`n"
}

Add-Section -Title "docker-compose.yml MCP sections" -Body {
    Select-String -Path (Join-Path $RepoRoot "docker-compose.yml") -Pattern "dockerfile:" -Context 2,2 | Out-String
}

Add-Section -Title "Host dev processes" -Body {
    $procFile = Join-Path $PSScriptRoot ".dev\processes.json"
    if (Test-Path -LiteralPath $procFile) { Get-Content -LiteralPath $procFile -Raw }
    else { "no scripts/.dev/processes.json" }
}

# -----------------------------------------------------------------------------
# Запись
# -----------------------------------------------------------------------------
$text = Protect-Secrets -Text $sb.ToString()
$text | Out-File -FilePath $OutPath -Encoding UTF8

Write-Host ""
Write-Host "Report saved: $OutPath" -ForegroundColor Green
Write-Host "Секреты вырезаны (Bearer / sk-* / password / api_key / token / PEM)." -ForegroundColor DarkGray
Write-Host "Приложите файл к обращению — по нему видно, где рассинхрон." -ForegroundColor DarkGray
Write-Host ""

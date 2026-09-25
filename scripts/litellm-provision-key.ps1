#Requires -Version 5.1
<#
.SYNOPSIS
    Provisions (or repairs) the scoped LiteLLM virtual key used by palatium-ai.

.DESCRIPTION
    The app talks to the Gateway with PALATIUM_GATEWAY_KEY. LiteLLM accepts ONLY:
      * the master key (LITELLM_MASTER_KEY), or
      * a key registered in the DB (LiteLLM_VerificationToken).
    The placeholder "sk-palatium-app" is created nowhere -> every LLM call fails with
        AuthenticationError ... token_not_found_in_db (401).
    This script makes the key real and idempotent:
      1) reads env/.env (LITELLM_MASTER_KEY, LITELLM_PUBLISH_PORT);
      2) if the current PALATIUM_GATEWAY_KEY already authenticates (GET /v1/models = 200)
         it exits without touching anything;
      3) otherwise mints a scoped virtual key via POST /key/generate
         (alias=palatium-app, models = tier-* from deploy/litellm/config.yaml);
      4) writes the key back into env/.env.

    Requires LiteLLM to run with database_url (virtual keys are stored in Postgres);
    without it only the master key can be used and this script stops with guidance.

    After the script updates env/.env, recreate the API so it picks the new secret:
        docker compose --env-file env/.env up -d --force-recreate api
    (host profile: .\scripts\dev-up.ps1 re-reads env/.env itself)

.PARAMETER EnvFile
    Env-файл (по умолчанию env/.env).

.PARAMETER GatewayUrl
    Явный базовый URL Gateway. По умолчанию http://127.0.0.1:${LITELLM_PUBLISH_PORT}.

.PARAMETER KeyAlias
    Alias виртуального ключа (по умолчанию palatium-app).

.PARAMETER Rotate
    Принудительно выпустить новый ключ даже если текущий валиден
    (старые ключи с тем же alias удаляются, best-effort).

.EXAMPLE
    .\scripts\litellm-provision-key.ps1
    .\scripts\litellm-provision-key.ps1 -Rotate
    .\scripts\litellm-provision-key.ps1 -EnvFile env/.env.staging
#>

[CmdletBinding()]
param(
    [string]$EnvFile = "env/.env",
    [string]$GatewayUrl = "",
    [string]$KeyAlias = "palatium-app",
    [switch]$Rotate
)

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

# =============================================================================
# Пути
# =============================================================================
$RepoRoot = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
$EnvPath  = Join-Path $RepoRoot $EnvFile
$ConfigPath = Join-Path $RepoRoot "deploy/litellm/config.yaml"
$Utf8NoBom = New-Object System.Text.UTF8Encoding($false)

if (-not (Test-Path $EnvPath)) {
    throw "ENV_FILE not found: $EnvPath. Copy from env/.env.example and fill in secrets."
}

# =============================================================================
# Хелперы .env
# =============================================================================
function Read-DotEnv {
    param([Parameter(Mandatory = $true)][string]$Path)
    $map = @{}
    foreach ($raw in [System.IO.File]::ReadAllLines($Path, [System.Text.Encoding]::UTF8)) {
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

function Set-DotEnvValue {
    param(
        [Parameter(Mandatory = $true)][string]$Path,
        [Parameter(Mandatory = $true)][string]$Key,
        [Parameter(Mandatory = $true)][string]$Value
    )
    $lines  = [System.IO.File]::ReadAllLines($Path, [System.Text.Encoding]::UTF8)
    $pattern = "^\s*#?\s*" + [regex]::Escape($Key) + "\s*="
    $found  = $false
    $out    = New-Object System.Collections.Generic.List[string]
    foreach ($l in $lines) {
        if ($l -match $pattern) {
            $out.Add("$Key=`"$Value`"")
            $found = $true
        } else {
            $out.Add($l)
        }
    }
    if (-not $found) {
        $out.Add("$Key=`"$Value`"")
    }
    [System.IO.File]::WriteAllLines($Path, $out, $Utf8NoBom)
}

# =============================================================================
# Хелперы HTTP
# =============================================================================
function Invoke-LiteLLMApi {
    param(
        [Parameter(Mandatory = $true)][string]$Method,
        [Parameter(Mandatory = $true)][string]$Url,
        [Parameter(Mandatory = $true)][string]$Bearer,
        [string]$JsonBody = ""
    )
    $headers = @{ Authorization = "Bearer $Bearer" }
    $params = @{
        Method          = $Method
        Uri             = $Url
        Headers         = $headers
        TimeoutSec      = 30
        UseBasicParsing = $true
        ErrorAction     = "Stop"
    }
    if ($JsonBody) {
        $params["Body"]        = $JsonBody
        $params["ContentType"] = "application/json"
    }
    try {
        $resp = Invoke-WebRequest @params
        $data = $null
        if ($resp.Content) { $data = $resp.Content | ConvertFrom-Json }
        return [pscustomobject]@{ ok = $true; status = [int]$resp.StatusCode; data = $data; error = "" }
    } catch {
        $status = 0
        $body   = ""
        if ($_.Exception.Response) {
            $status = [int]$_.Exception.Response.StatusCode
            try {
                $stream = $_.Exception.Response.GetResponseStream()
                $reader = New-Object System.IO.StreamReader($stream)
                $body   = $reader.ReadToEnd()
            } catch { $body = "" }
        }
        if (-not $body) { $body = $_.Exception.Message }
        return [pscustomobject]@{ ok = $false; status = $status; data = $null; error = $body }
    }
}

function Get-TierModels {
    param([Parameter(Mandatory = $true)][string]$ConfigFile)
    $models = New-Object System.Collections.Generic.List[string]
    if (Test-Path $ConfigFile) {
        foreach ($line in [System.IO.File]::ReadAllLines($ConfigFile, [System.Text.Encoding]::UTF8)) {
            $m = [regex]::Match($line, '^\s*-\s*model_name:\s*([A-Za-z0-9._-]+)')
            if ($m.Success) {
                $name = $m.Groups[1].Value.Trim()
                if (-not $models.Contains($name)) { $models.Add($name) }
            }
        }
    }
    if ($models.Count -eq 0) {
        # Fallback: keep in sync with deploy/litellm/config.yaml model_list.
        foreach ($name in @("tier-nano", "tier-small", "tier-mid", "tier-frontier", "tier-deep")) {
            $models.Add($name)
        }
    }
    return $models.ToArray()
}

# =============================================================================
# Preflight
# =============================================================================
$DotEnv = Read-DotEnv -Path $EnvPath

$masterKey = ""
if ($DotEnv.ContainsKey("LITELLM_MASTER_KEY")) { $masterKey = [string]$DotEnv["LITELLM_MASTER_KEY"] }
if (-not $masterKey) {
    throw "LITELLM_MASTER_KEY is empty in $EnvFile. Set it (see env/.env.example) before provisioning."
}

$llmPort = 4000
if ($DotEnv.ContainsKey("LITELLM_PUBLISH_PORT") -and $DotEnv["LITELLM_PUBLISH_PORT"] -match '^\d+$') {
    $llmPort = [int]$DotEnv["LITELLM_PUBLISH_PORT"]
}

$baseUrl = $GatewayUrl
if (-not $baseUrl) { $baseUrl = "http://127.0.0.1:$llmPort" }
$baseUrl = $baseUrl.TrimEnd("/")

$currentKey = ""
if ($DotEnv.ContainsKey("PALATIUM_GATEWAY_KEY")) { $currentKey = [string]$DotEnv["PALATIUM_GATEWAY_KEY"] }

Write-Host ""
Write-Host "LiteLLM key provisioning" -ForegroundColor Cyan
Write-Host "  env:      $EnvFile"
Write-Host "  gateway:  $baseUrl"
Write-Host "  alias:    $KeyAlias"

# --- 1. Уже валиден? ---------------------------------------------------------
if ($currentKey -and -not $Rotate) {
    $probe = Invoke-LiteLLMApi -Method GET -Url "$baseUrl/v1/models" -Bearer $currentKey
    if ($probe.ok) {
        Write-Host "  [ok]   PALATIUM_GATEWAY_KEY уже валиден — изменений не требуется." -ForegroundColor Green
        exit 0
    }
    Write-Host "  [warn] текущий PALATIUM_GATEWAY_KEY отклонён (HTTP $($probe.status)) — выпускаю новый." -ForegroundColor Yellow
}

# --- 2. Rotate: удалить старые ключи с тем же alias (best-effort) ------------
if ($Rotate -and $currentKey) {
    try {
        $list = Invoke-LiteLLMApi -Method GET -Url "$baseUrl/key/list?key_alias=$KeyAlias&return_full_object=true" -Bearer $masterKey
        if ($list.ok -and $list.data -and $list.data.keys) {
            $tokens = @()
            foreach ($entry in $list.data.keys) {
                if ($entry -is [string]) { $tokens += $entry }
                elseif ($entry.PSObject.Properties.Name -contains "token") { $tokens += [string]$entry.token }
            }
            if ($tokens.Count -gt 0) {
                $delBody = @{ keys = $tokens } | ConvertTo-Json -Compress
                $null = Invoke-LiteLLMApi -Method POST -Url "$baseUrl/key/delete" -Bearer $masterKey -JsonBody $delBody
                Write-Host "  [info] удалено старых ключей alias=$KeyAlias : $($tokens.Count)" -ForegroundColor DarkGray
            }
        }
    } catch {
        Write-Host "  [warn] не удалось очистить старые ключи alias=$KeyAlias (не критично)." -ForegroundColor DarkYellow
    }
}

# --- 3. Создать scoped virtual key ------------------------------------------
$tierModels = Get-TierModels -ConfigFile $ConfigPath
$body = @{
    key_alias = $KeyAlias
    models    = $tierModels
    metadata  = @{ managed_by = "palatium-ai"; purpose = "app-gateway" }
} | ConvertTo-Json -Depth 5 -Compress

$create = Invoke-LiteLLMApi -Method POST -Url "$baseUrl/key/generate" -Bearer $masterKey -JsonBody $body
if (-not $create.ok) {
    $hint = ""
    if ($create.status -eq 401) {
        $hint = " Проверьте LITELLM_MASTER_KEY и что LiteLLM запущен с LITELLM_DB_URL."
    } elseif ($create.status -eq 500 -and $create.error -match "database|DB|relation") {
        $hint = " LiteLLM работает без database_url — virtual keys недоступны; включите LITELLM_DB_URL."
    }
    throw "POST /key/generate failed (HTTP $($create.status)): $($create.error).$hint"
}

$newKey = ""
if ($create.data -and ($create.data.PSObject.Properties.Name -contains "key")) {
    $newKey = [string]$create.data.key
}
if (-not $newKey -or -not $newKey.StartsWith("sk-")) {
    throw "LiteLLM вернул неожиданный ответ без поля 'key'. Проверьте версию Gateway."
}

Set-DotEnvValue -Path $EnvPath -Key "PALATIUM_GATEWAY_KEY" -Value $newKey
Write-Host "  [ok]   создан virtual key (alias=$KeyAlias, models=$($tierModels -join ','))" -ForegroundColor Green
Write-Host "  [ok]   PALATIUM_GATEWAY_KEY обновлён в $EnvFile" -ForegroundColor Green
Write-Host ""
Write-Host "Дальше:" -ForegroundColor Cyan
Write-Host "  docker compose --env-file $EnvFile up -d --force-recreate api" -ForegroundColor Gray
Write-Host "  # или host-профиль:  .\scripts\dev-up.ps1" -ForegroundColor Gray
Write-Host ""

# scripts/menu.ps1
# Palatium-AI Control Panel — операторский интерфейс без мерцания.
#
# Keys:
#   ↑ / ↓      навигация
#   Enter      выполнить
#   1..9,a..l  прямой хоткей
#   R          обновить статус (force)
#   Q / Esc    выход
#
# Flicker-free rendering: ANSI cursor positioning, no Clear-Host.
# Status snapshot cache: 3s TTL — навигация не тормозит.
#
# Запуск: .\scripts\menu.ps1

[CmdletBinding()]
param(
    [string]$EnvFile = "env/.env"
)

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

$Script:RepoRoot   = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
$Script:AppVersion = "0.1.0"
$Script:Exit       = $false

# =============================================================================
# Terminal preflight
# =============================================================================
try {
    if ([Console]::BufferHeight -lt 120) {
        [Console]::BufferHeight = 200
    }
} catch { }

# =============================================================================
# Палитра
# =============================================================================
$C_Accent = "Cyan"
$C_Header = "Cyan"
$C_Ok     = "Green"
$C_Warn   = "Yellow"
$C_Err    = "Red"
$C_Muted  = "DarkGray"
$C_Text   = "Gray"
$C_SelBg  = "DarkCyan"
$C_SelFg  = "White"

# =============================================================================
# Status cache
# =============================================================================
$Script:SnapCache     = $null
$Script:SnapCacheTime = [DateTime]::MinValue
$Script:SnapCacheTtl  = 3

# =============================================================================
# Flicker-free renderer
# =============================================================================
$Script:Width = 100

function Get-TermWidth {
    try { return [Math]::Max(80, [Console]::WindowWidth - 1) } catch { return 100 }
}

function Write-Row {
    param(
        [Parameter(Mandatory = $true)][int]$Row,
        [string]$Text = "",
        [string]$Fg = "Gray",
        [string]$Bg = ""
    )
    $maxRow = [Console]::BufferHeight - 1
    if ($Row -lt 0 -or $Row -gt $maxRow) { return }

    $pad = $Script:Width - $Text.Length
    if ($pad -lt 0) { $pad = 0 }
    $line = $Text + (" " * $pad)

    [Console]::SetCursorPosition(0, $Row)
    if ($Bg) {
        Write-Host $line -ForegroundColor $Fg -BackgroundColor $Bg -NoNewline
    } else {
        Write-Host $line -ForegroundColor $Fg -NoNewline
    }
}

function Write-RowSegments {
    param(
        [Parameter(Mandatory = $true)][int]$Row,
        [Parameter(Mandatory = $true)][array]$Segments
    )
    $maxRow = [Console]::BufferHeight - 1
    if ($Row -lt 0 -or $Row -gt $maxRow) { return }

    [Console]::SetCursorPosition(0, $Row)
    $used = 0
    foreach ($seg in $Segments) {
        $t  = ""
        $fg = "Gray"
        $bg = ""

        if ($seg -is [hashtable]) {
            if ($seg.ContainsKey("Text") -and $null -ne $seg["Text"]) { $t  = [string]$seg["Text"] }
            if ($seg.ContainsKey("Fg")   -and $null -ne $seg["Fg"])   { $fg = [string]$seg["Fg"] }
            if ($seg.ContainsKey("Bg")   -and $null -ne $seg["Bg"])   { $bg = [string]$seg["Bg"] }
        } elseif ($seg -is [string]) {
            $t = [string]$seg
        }

        $used += $t.Length

        if ($bg) {
            Write-Host $t -ForegroundColor $fg -BackgroundColor $bg -NoNewline
        } else {
            Write-Host $t -ForegroundColor $fg -NoNewline
        }
    }
    if ($used -lt $Script:Width) {
        Write-Host (" " * ($Script:Width - $used)) -NoNewline
    }
}

# =============================================================================
# Compose wrapper
# =============================================================================
function Invoke-Compose {
    param([Parameter(ValueFromRemainingArguments = $true)][string[]]$Args)
    docker compose --env-file $EnvFile @Args
}

function Pause-Return {
    $maxRow = [Console]::BufferHeight - 1
    $row = [Console]::CursorTop
    if ($row -gt $maxRow - 3) { $row = $maxRow - 3 }
    if ($row -lt 0) { $row = 0 }

    Write-Row -Row $row -Text "" -Fg $C_Muted
    Write-Row -Row ($row + 1) -Text "  Enter — назад в меню" -Fg $C_Muted
    [Console]::SetCursorPosition(0, $row + 2)
    try { [Console]::CursorVisible = $true } catch {}
    Read-Host | Out-Null
    try { [Console]::CursorVisible = $false } catch {}
}

# =============================================================================
# Status probes
# =============================================================================
function Test-PortListening {
    param([int]$Port)
    return [bool](Get-NetTCPConnection -LocalPort $Port -State Listen -ErrorAction SilentlyContinue |
        Select-Object -First 1)
}

function Test-Health {
    param([string]$Url)
    try {
        $r = Invoke-WebRequest -Uri $Url -TimeoutSec 1 -UseBasicParsing -ErrorAction Stop
        return ($r.StatusCode -eq 200)
    } catch { return $false }
}

function Get-StatusSnapshot {
    param([switch]$Force)

    $now = Get-Date
    if (-not $Force -and $Script:SnapCache -and
        ($now - $Script:SnapCacheTime).TotalSeconds -lt $Script:SnapCacheTtl) {
        return $Script:SnapCache
    }

    $snap = [ordered]@{
        Postgres     = Test-PortListening 5432
        Redis        = Test-PortListening 6379
        Neo4j        = Test-PortListening 7474
        LiteLLM      = Test-PortListening 4000
        Api          = Test-PortListening 8000
        McpEdms      = Test-PortListening 8080
        McpAnalytics = Test-PortListening 8081
    }
    if ($snap.Api)     { $snap.Api_health     = Test-Health "http://127.0.0.1:8000/health" }
    if ($snap.LiteLLM) { $snap.LiteLLM_health = Test-Health "http://127.0.0.1:4000/health/liveliness" }

    $Script:SnapCache     = $snap
    $Script:SnapCacheTime = $now
    return $snap
}

function Get-StatusColor {
    param([bool]$Up, [bool]$HealthOk = $true)
    if (-not $Up)       { return $C_Err }
    if (-not $HealthOk) { return $C_Warn }
    return $C_Ok
}

function Get-StatusText {
    param([bool]$Up, [bool]$HealthOk = $true)
    if (-not $Up)       { return "DOWN" }
    if (-not $HealthOk) { return "DEGRADED" }
    return "UP"
}

# =============================================================================
# Actions — Стек
# =============================================================================
function Invoke-InfraUp {
    Write-Host "`n[ infra:up ] postgres redis neo4j litellm" -ForegroundColor $C_Accent
    Invoke-Compose up -d postgres redis neo4j litellm
    Invoke-Compose ps
    $null = Get-StatusSnapshot -Force
}

function Invoke-HostUp {
    Write-Host "`n[ host:up ] dev-up.ps1" -ForegroundColor $C_Accent
    & "$Script:RepoRoot\scripts\dev-up.ps1"
    $null = Get-StatusSnapshot -Force
}

function Invoke-HostDown {
    Write-Host "`n[ host:down ] dev-down.ps1 -Force" -ForegroundColor $C_Accent
    & "$Script:RepoRoot\scripts\dev-down.ps1" -Force
    $null = Get-StatusSnapshot -Force
}

function Invoke-FullStackUp {
    Write-Host "`n[ full:up ] profile docker-mcp+docker-api" -ForegroundColor $C_Accent
    Invoke-Compose --profile docker-mcp --profile docker-api up -d --build
    Invoke-Compose --profile docker-mcp --profile docker-api ps
    $null = Get-StatusSnapshot -Force
}

function Invoke-StackDown {
    Write-Host "`n[ stack:down ]" -ForegroundColor $C_Accent
    Invoke-Compose down
    $null = Get-StatusSnapshot -Force
}

function Invoke-StackReset {
    Write-Host "`n[ stack:reset — DESTRUCTIVE ]" -ForegroundColor $C_Err
    Write-Host "  Все volumes (Postgres / Redis / Neo4j) будут удалены." -ForegroundColor $C_Warn
    try { [Console]::CursorVisible = $true } catch {}
    $c = Read-Host "  Продолжить? (yes/N)"
    try { [Console]::CursorVisible = $false } catch {}
    if ($c -eq "yes") {
        Invoke-Compose down -v
        Write-Host "  Volumes удалены." -ForegroundColor $C_Ok
        $null = Get-StatusSnapshot -Force
    } else {
        Write-Host "  Отменено." -ForegroundColor $C_Muted
    }
}

# =============================================================================
# Actions — Диагностика
# =============================================================================
function Invoke-StatusShow {
    Write-Host "`n[ status ]" -ForegroundColor $C_Accent
    Invoke-Compose ps
}
function Invoke-LogsAll {
    Write-Host "`n[ logs:all ] Ctrl+C для выхода`n" -ForegroundColor $C_Accent
    Invoke-Compose logs -f
}
function Invoke-LogsLitellm {
    Write-Host "`n[ logs:litellm ] Ctrl+C для выхода`n" -ForegroundColor $C_Accent
    Invoke-Compose logs -f litellm
}
function Invoke-LogsApi {
    Write-Host "`n[ logs:api ] Ctrl+C для выхода`n" -ForegroundColor $C_Accent
    Invoke-Compose logs -f api
}

# =============================================================================
# Actions — Проверка
# =============================================================================
function Invoke-VerifyEndpoints {
    Write-Host "`n[ verify ]" -ForegroundColor $C_Accent
    $checks = @(
        @{ Name = "API /health";         Url = "http://127.0.0.1:8000/health" },
        @{ Name = "API /docs";           Url = "http://127.0.0.1:8000/docs" },
        @{ Name = "LiteLLM /liveliness"; Url = "http://127.0.0.1:4000/health/liveliness" },
        @{ Name = "MCP EDMS";            Url = "http://127.0.0.1:8080/health" },
        @{ Name = "MCP Analytics";       Url = "http://127.0.0.1:8081/health" }
    )
    foreach ($c in $checks) {
        try {
            $r = Invoke-WebRequest -Uri $c.Url -TimeoutSec 3 -UseBasicParsing -ErrorAction Stop
            Write-Host ("  {0,-24} {1}" -f $c.Name, "OK $($r.StatusCode)") -ForegroundColor $C_Ok
        } catch {
            Write-Host ("  {0,-24} {1}" -f $c.Name, "FAIL") -ForegroundColor $C_Err
        }
    }
}

function Invoke-GatewayTest {
    Write-Host "`n[ gateway:test tier-mid ]" -ForegroundColor $C_Accent
    $body = @{
        model    = "tier-mid"
        messages = @(@{ role = "user"; content = "Say OK" })
    } | ConvertTo-Json -Depth 5 -Compress
    try {
        $r = Invoke-RestMethod -Uri "http://127.0.0.1:4000/v1/chat/completions" `
            -Method Post `
            -Headers @{
                Authorization  = "Bearer sk-palatium-master"
                "Content-Type" = "application/json"
            } `
            -Body $body -TimeoutSec 30
        Write-Host "  model:  $($r.model)" -ForegroundColor $C_Ok
        Write-Host "  reply:  $($r.choices[0].message.content)" -ForegroundColor $C_Ok
    } catch {
        Write-Host "  FAIL: $($_.Exception.Message)" -ForegroundColor $C_Err
    }
}

function Invoke-GatewayModels {
    Write-Host "`n[ gateway:models ]" -ForegroundColor $C_Accent
    try {
        $r = Invoke-RestMethod -Uri "http://127.0.0.1:4000/v1/models" `
            -Headers @{ Authorization = "Bearer sk-palatium-master" } -TimeoutSec 5
        foreach ($m in $r.data) {
            Write-Host "  • $($m.id)" -ForegroundColor $C_Ok
        }
    } catch {
        Write-Host "  FAIL: $($_.Exception.Message)" -ForegroundColor $C_Err
    }
}

function Invoke-ComposeValidate {
    Write-Host "`n[ compose:validate ]" -ForegroundColor $C_Accent
    Invoke-Compose config --quiet
    if ($LASTEXITCODE -eq 0) {
        Write-Host "  OK: docker-compose.yml валиден" -ForegroundColor $C_Ok
    } else {
        Write-Host "  FAIL" -ForegroundColor $C_Err
    }
}

# =============================================================================
# Actions — БД
# =============================================================================
function Invoke-DbList {
    Write-Host "`n[ db:list ]" -ForegroundColor $C_Accent
    Invoke-Compose exec postgres psql -U postgres -c "\l"
}
function Invoke-DbSchemas {
    Write-Host "`n[ db:schemas ]" -ForegroundColor $C_Accent
    Invoke-Compose exec postgres psql -U postgres -d postgres -c "\dn"
}
function Invoke-DbExtensions {
    Write-Host "`n[ db:extensions ]" -ForegroundColor $C_Accent
    Invoke-Compose exec postgres psql -U postgres -d postgres -c "\dx"
}
function Invoke-DbMigrations {
    Write-Host "`n[ alembic:upgrade head ]" -ForegroundColor $C_Accent
    Invoke-Compose exec api alembic upgrade head
}

# =============================================================================
# Actions — Интерфейс
# =============================================================================
function Invoke-OpenSwagger   { Start-Process "http://127.0.0.1:8000/docs" }
function Invoke-OpenLiteLLMUI { Start-Process "http://127.0.0.1:4000/ui" }
function Invoke-OpenNeo4jUI   { Start-Process "http://127.0.0.1:7474" }

# =============================================================================
# Menu model
# =============================================================================
$MenuSections = @(
    [pscustomobject]@{
        Title = "УПРАВЛЕНИЕ СТЕКОМ"
        Items = @(
            @{ Key = "1"; Label = "Инфраструктура (Docker)";   Hint = "postgres redis neo4j litellm";  Action = { Invoke-InfraUp } }
            @{ Key = "2"; Label = "Host-стек (Poetry)";         Hint = "dev-up.ps1";                    Action = { Invoke-HostUp } }
            @{ Key = "3"; Label = "Full Docker (prod-like)";    Hint = "profile docker-mcp+docker-api"; Action = { Invoke-FullStackUp } }
            @{ Key = "4"; Label = "Остановить Docker";          Hint = "down";                          Action = { Invoke-StackDown } }
            @{ Key = "5"; Label = "Остановить host";            Hint = "dev-down.ps1 -Force";           Action = { Invoke-HostDown } }
            @{ Key = "6"; Label = "Сброс + volumes";            Hint = "down -v (DESTRUCTIVE)";         Action = { Invoke-StackReset } }
        )
    }
    [pscustomobject]@{
        Title = "ДИАГНОСТИКА"
        Items = @(
            @{ Key = "7"; Label = "Статус сервисов";  Hint = "docker compose ps"; Action = { Invoke-StatusShow } }
            @{ Key = "8"; Label = "Логи: все";        Hint = "logs -f";           Action = { Invoke-LogsAll } }
            @{ Key = "9"; Label = "Логи: litellm";    Hint = "logs -f litellm";   Action = { Invoke-LogsLitellm } }
            @{ Key = "a"; Label = "Логи: api";        Hint = "logs -f api";       Action = { Invoke-LogsApi } }
        )
    }
    [pscustomobject]@{
        Title = "ПРОВЕРКА"
        Items = @(
            @{ Key = "b"; Label = "Проверить endpoints";   Hint = "HTTP health-check"; Action = { Invoke-VerifyEndpoints } }
            @{ Key = "c"; Label = "Тест gateway tier-mid"; Hint = "chat.completions";  Action = { Invoke-GatewayTest } }
            @{ Key = "d"; Label = "Модели LiteLLM";        Hint = "GET /v1/models";    Action = { Invoke-GatewayModels } }
            @{ Key = "e"; Label = "Валидация compose";     Hint = "config --quiet";    Action = { Invoke-ComposeValidate } }
        )
    }
    [pscustomobject]@{
        Title = "БАЗА ДАННЫХ"
        Items = @(
            @{ Key = "f"; Label = "Список БД";            Hint = "\l";          Action = { Invoke-DbList } }
            @{ Key = "g"; Label = "Схемы";                Hint = "\dn";         Action = { Invoke-DbSchemas } }
            @{ Key = "h"; Label = "Расширения";           Hint = "\dx";         Action = { Invoke-DbExtensions } }
            @{ Key = "i"; Label = "Alembic upgrade head"; Hint = "migrations";  Action = { Invoke-DbMigrations } }
        )
    }
    [pscustomobject]@{
        Title = "ИНТЕРФЕЙС"
        Items = @(
            @{ Key = "j"; Label = "Swagger UI";    Hint = ":8000/docs"; Action = { Invoke-OpenSwagger } }
            @{ Key = "k"; Label = "LiteLLM UI";    Hint = ":4000/ui";   Action = { Invoke-OpenLiteLLMUI } }
            @{ Key = "l"; Label = "Neo4j Browser"; Hint = ":7474";      Action = { Invoke-OpenNeo4jUI } }
        )
    }
)

# Flatten
$Flat = @()
foreach ($sec in $MenuSections) {
    foreach ($it in $sec.Items) {
        $Flat += [pscustomobject]@{
            Section = $sec.Title
            Key     = $it.Key
            Label   = $it.Label
            Hint    = $it.Hint
            Action  = $it.Action
        }
    }
}
$Flat += [pscustomobject]@{ Section = "SYSTEM"; Key = "q"; Label = "Выход"; Hint = "exit"; Action = { $Script:Exit = $true } }

# =============================================================================
# Render (flicker-free)
# =============================================================================
function Render-StatusBar {
    param([int]$StartRow, $Snap)
    $row = $StartRow
    Write-RowSegments -Row $row -Segments @(
        @{ Text = " СТАТУС  ";                   Fg = $C_Header }
        @{ Text = (Get-Date -Format "HH:mm:ss"); Fg = $C_Muted }
    )
    $row++

    $pairs = @(
        @("PG",   $Snap.Postgres,       $true),
        @("RDS",  $Snap.Redis,          $true),
        @("NEO",  $Snap.Neo4j,          $true),
        @("LLM",  $Snap.LiteLLM,        $(if ($Snap.Contains("LiteLLM_health")) { $Snap.LiteLLM_health } else { $true })),
        @("API",  $Snap.Api,            $(if ($Snap.Contains("Api_health"))     { $Snap.Api_health }     else { $true })),
        @("MEDMS",$Snap.McpEdms,        $true),
        @("MAN",  $Snap.McpAnalytics,   $true)
    )

    $segments = @()
    foreach ($p in $pairs) {
        $name  = $p[0]
        $up    = [bool]$p[1]
        $ok    = [bool]$p[2]
        $color = Get-StatusColor -Up $up -HealthOk $ok

        $segments += @{ Text = (" {0}:" -f $name); Fg = $C_Text }
        $segments += @{ Text = "●";                 Fg = $color }
        $segments += @{ Text = " ";                 Fg = $C_Text }
    }
    Write-RowSegments -Row $row -Segments $segments
    $row++

    return $row
}

function Render-MenuBody {
    param([int]$StartRow, [int]$Selected)
    $row = $StartRow
    $i = 0

    foreach ($sec in $MenuSections) {
        $title = "  " + $sec.Title + "  "
        $line  = $title + ("─" * ([Math]::Max(0, $Script:Width - $title.Length - 2)))
        Write-Row -Row $row -Text $line -Fg $C_Header
        $row++

        foreach ($item in $sec.Items) {
            $flatIdx = $i
            $isSel   = ($flatIdx -eq $Selected)
            $keyTag  = "[{0}]" -f $item.Key
            $label   = "{0,-30}" -f $item.Label
            $hint    = $item.Hint

            if ($isSel) {
                Write-RowSegments -Row $row -Segments @(
                    @{ Text = "  ► ";                                       Fg = $C_Warn }
                    @{ Text = (" {0} {1} " -f $keyTag, $label);              Fg = $C_SelFg; Bg = $C_SelBg }
                    @{ Text = ("  {0}" -f $hint);                            Fg = $C_Muted }
                )
            } else {
                Write-RowSegments -Row $row -Segments @(
                    @{ Text = "    " }
                    @{ Text = (" {0} " -f $keyTag); Fg = $C_Accent }
                    @{ Text = $label;                Fg = $C_Text }
                    @{ Text = ("  {0}" -f $hint);    Fg = $C_Muted }
                )
            }
            $row++
            $i++
        }
        Write-Row -Row $row -Text ""
        $row++
    }

    # Exit row
    $isExit = ($Selected -eq $Flat.Count - 1)
    if ($isExit) {
        Write-RowSegments -Row $row -Segments @(
            @{ Text = "  ► ";                Fg = $C_Warn }
            @{ Text = " [Q] Выход ";         Fg = $C_SelFg; Bg = $C_SelBg }
        )
    } else {
        Write-RowSegments -Row $row -Segments @(
            @{ Text = "    " }
            @{ Text = " [Q] ";               Fg = $C_Accent }
            @{ Text = "Выход";                Fg = $C_Text }
        )
    }
    $row++

    Write-Row -Row $row -Text ""
    $row++
    Write-Row -Row $row -Text "  ↑/↓ — навигация   Enter — выполнить   R — обновить   Q — выход" -Fg $C_Muted

    return $row + 1
}

function Render-Frame {
    param([int]$Selected)
    $Script:Width = Get-TermWidth

    $snap = Get-StatusSnapshot

    # Header
    $row = 0
    Write-RowSegments -Row $row -Segments @(
        @{ Text = "  PALATIUM-AI  ·  CONTROL PANEL"; Fg = $C_Header }
        @{ Text = ("                            v{0}" -f $Script:AppVersion); Fg = $C_Muted }
    )
    $row++
    Write-Row -Row $row -Text ("  env: {0}" -f $EnvFile) -Fg $C_Muted
    $row++

    # Status (compact)
    $row = Render-StatusBar -StartRow $row -Snap $snap
    Write-Row -Row $row -Text ""; $row++

    # Body
    $row = Render-MenuBody -StartRow $row -Selected $Selected

    # Clear remaining
    $h = [Console]::BufferHeight - 1
    while ($row -lt $h) {
        Write-Row -Row $row -Text ""
        $row++
    }
}

# =============================================================================
# Main loop
# =============================================================================
$Script:Width = Get-TermWidth
try { [Console]::CursorVisible = $false } catch {}

$selected = 0

try {
    while (-not $Script:Exit) {
        Render-Frame -Selected $selected

        $key = [Console]::ReadKey($true)

        switch ($key.Key) {
            "UpArrow"   { $selected = ($selected - 1 + $Flat.Count) % $Flat.Count; continue }
            "DownArrow" { $selected = ($selected + 1) % $Flat.Count;              continue }
            "Enter" {
                try { [Console]::CursorVisible = $true } catch {}
                $safeRow = [Math]::Max(0, [Console]::BufferHeight - 3)
                [Console]::SetCursorPosition(0, $safeRow)
                Write-Host ""
                & $Flat[$selected].Action
                if (-not $Script:Exit) { Pause-Return }
                try { [Console]::CursorVisible = $false } catch {}
                continue
            }
            "Escape" { $Script:Exit = $true; continue }
        }

        $ch = $key.KeyChar.ToString().ToLower()
        if ($ch -eq 'q') { $Script:Exit = $true; continue }
        if ($ch -eq 'r') {
            $null = Get-StatusSnapshot -Force
            continue
        }
        if ($ch -match '^[a-z0-9]$') {
            $hit = $Flat | Where-Object { $_.Key -eq $ch } | Select-Object -First 1
            if ($hit) {
                try { [Console]::CursorVisible = $true } catch {}
                $safeRow = [Math]::Max(0, [Console]::BufferHeight - 3)
                [Console]::SetCursorPosition(0, $safeRow)
                Write-Host ""
                & $hit.Action
                if (-not $Script:Exit) { Pause-Return }
                try { [Console]::CursorVisible = $false } catch {}
            }
        }
    }
}
finally {
    try { [Console]::CursorVisible = $true } catch {}
    Clear-Host
    Write-Host ""
    Write-Host "  Palatium-AI Control Panel — выход." -ForegroundColor $C_Muted
    Write-Host ""
}

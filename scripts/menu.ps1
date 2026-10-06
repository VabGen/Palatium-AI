# scripts/menu.ps1 — Palatium-AI · Control Panel
# ===========================================================================
# Get-ChildItem "$env:LOCALAPPDATA\Microsoft\WinGet\Packages" `
# >>     -Recurse -Filter "gum.exe" -ErrorAction SilentlyContinue |
# >>     Select-Object -ExpandProperty FullName
# ---------------------------------------------------------------------------
# $env:PATH = [Environment]::GetEnvironmentVariable("PATH","User") + ";" +
# >>             [Environment]::GetEnvironmentVariable("PATH","Machine")
# ---------------------------------------------------------------------------
# gum --version
# ===========================================================================
$ErrorActionPreference = "Stop"
[Console]::OutputEncoding = [System.Text.Encoding]::UTF8

if (-not (Get-Command gum -ErrorAction SilentlyContinue)) {
    Write-Host "gum not found. Run: .\scripts\setup-gum-path.ps1" -ForegroundColor Red
    exit 1
}

# ── Context ────────────────────────────────────────────────────────────────
$root    = Split-Path -Parent $PSScriptRoot
$envFile = if ($env:ENV_FILE) { $env:ENV_FILE } else { "env/.env" }

$masterKey = $env:LITELLM_MASTER_KEY
if (-not $masterKey -and (Test-Path (Join-Path $root $envFile))) {
    $line = Select-String -Path (Join-Path $root $envFile) `
        -Pattern '^LITELLM_MASTER_KEY=' | Select-Object -First 1
    if ($line) { $masterKey = ($line.Line -split '=', 2)[1].Trim('"').Trim("'") }
}
if (-not $masterKey) { $masterKey = "sk-palatium-master" }

function Invoke-Compose {
    param([Parameter(ValueFromRemainingArguments = $true)] [string[]] $Rest)
    docker compose --env-file $envFile --profile docker-mcp --profile docker-api @Rest
}

# Optional profiles are added on top of the base pair: `api` lives behind
# docker-api and `clamav`/`minio` behind their own profiles, so a bare
# `up -d clamav` would not keep the API in the same project (see docker-compose.override.yml).
function Invoke-ComposeExtra {
    param([string] $Profile, [Parameter(ValueFromRemainingArguments = $true)] [string[]] $Rest)
    docker compose --env-file $envFile --profile docker-mcp --profile docker-api --profile $Profile @Rest
}

function Invoke-ComposeAttachments {
    param([Parameter(ValueFromRemainingArguments = $true)] [string[]] $Rest)
    docker compose --env-file $envFile --profile docker-mcp --profile docker-api `
        --profile attachments --profile attachments-s3 @Rest
}

# ── Palette ────────────────────────────────────────────────────────────────
$C_HEAD  = "White"
$C_ACC   = "Cyan"
$C_TEXT  = "Gray"
$C_MUTE  = "DarkGray"
$C_OK    = "Green"
$C_ERR   = "Red"

# ── Animations ─────────────────────────────────────────────────────────────
function Invoke-WithSpinner {
    param(
        [string]$Title,
        [scriptblock]$Action,
        [object[]]$ArgumentList = @()
    )
    $frames = @("|","/","-","\")
    $i = 0
    # Arguments must be passed explicitly: Start-Job runs in a fresh process, so the
    # scriptblock cannot read $envFile/$root from this session (it would silently
    # expand to $null and the command would run against the wrong compose file).
    $job = Start-Job -ScriptBlock $Action -ArgumentList $ArgumentList
    while ($job.State -eq "Running") {
        Write-Host ("`r  {0} {1}   " -f $frames[$i % $frames.Length], $Title) `
            -NoNewline -ForegroundColor $C_ACC
        $i++
        Start-Sleep -Milliseconds 100
    }
    $out = Receive-Job $job -ErrorAction SilentlyContinue
    Remove-Job $job
    Write-Host ("`r  OK  {0}                    " -f $Title) -ForegroundColor $C_OK
    return $out
}

# ── Menu ───────────────────────────────────────────────────────────────────
$menu = @(
    @{ Type = "group"; Text = "STACK" }
    @{ Type = "item";  Text = "Start stack";            Hint = "up -d --build"; Key = "start" }
    @{ Type = "item";  Text = "Restart";                Hint = "up -d";         Key = "restart" }
    @{ Type = "item";  Text = "Stop stack";             Hint = "down";          Key = "stop" }
    @{ Type = "item";  Text = "Full reset (volumes)";   Hint = "down -v";       Key = "reset" }
    @{ Type = "group"; Text = "LOGS" }
    @{ Type = "item";  Text = "Logs  all";              Hint = "-f";            Key = "logs" }
    @{ Type = "item";  Text = "Logs  litellm";          Hint = "litellm";       Key = "logs-litellm" }
    @{ Type = "item";  Text = "Logs  api";              Hint = "api";           Key = "logs-api" }
    @{ Type = "group"; Text = "DIAGNOSTICS" }
    @{ Type = "item";  Text = "Service status";         Hint = "ps";            Key = "ps" }
    @{ Type = "item";  Text = "Check endpoints";        Hint = "health";        Key = "health" }
    @{ Type = "item";  Text = "Validate compose";       Hint = "config";        Key = "validate" }
    @{ Type = "item";  Text = "LiteLLM models";         Hint = "/v1/models";    Key = "models" }
    @{ Type = "item";  Text = "Test tier-mid";          Hint = "chat";          Key = "test-tier" }
    @{ Type = "item";  Text = "Alembic migrations";     Hint = "upgrade head";  Key = "migrate" }
    @{ Type = "item";  Text = "List Postgres DBs";      Hint = "psql";          Key = "list-dbs" }
    @{ Type = "group"; Text = "ATTACHMENTS" }
    @{ Type = "item";  Text = "Start AV engine";        Hint = "profile attachments";    Key = "attach-up" }
    @{ Type = "item";  Text = "Start S3 store";         Hint = "profile attachments-s3"; Key = "attach-s3-up" }
    @{ Type = "item";  Text = "Stop attachments";       Hint = "stop clamav+minio";      Key = "attach-down" }
    @{ Type = "item";  Text = "Probe attachments";      Hint = "api+clamd+s3";           Key = "attach-probe" }
    @{ Type = "item";  Text = "Logs  clamav";           Hint = "-f";                     Key = "attach-logs-av" }
    @{ Type = "item";  Text = "Logs  minio";            Hint = "-f";                     Key = "attach-logs-s3" }
    @{ Type = "group"; Text = "UTILITIES" }
    @{ Type = "item";  Text = "Shell  api";             Hint = "sh";            Key = "shell" }
    @{ Type = "item";  Text = "Open Swagger UI";        Hint = ":8000/docs";    Key = "swagger" }
    @{ Type = "item";  Text = "Open LiteLLM UI";        Hint = ":4000/ui";      Key = "litellm-ui" }
    @{ Type = "item";  Text = "Exit";                   Hint = "q";             Key = "exit" }
)

$selectable = 0..($menu.Count - 1) | Where-Object { $menu[$_].Type -eq "item" }

# ── Rendering ──────────────────────────────────────────────────────────────
function Write-MenuFrame {
    param([array]$Menu, [int[]]$Selectable, [int]$Pos, [int]$HintCol = 50)

    $w = [Math]::Max(60, [Console]::WindowWidth - 1)

    # Header (2 строки)
    Write-Host "  " -NoNewline
    Write-Host "▎ " -NoNewline -ForegroundColor $C_ACC
    Write-Host "PALATIUM-AI" -NoNewline -ForegroundColor $C_HEAD
    Write-Host "  ·  " -NoNewline -ForegroundColor $C_MUTE
    Write-Host "Control Panel" -ForegroundColor $C_HEAD
    Write-Host "  " -NoNewline
    Write-Host ("─" * ($w - 2)) -ForegroundColor $C_MUTE

    for ($i = 0; $i -lt $Menu.Count; $i++) {
        $row = $Menu[$i]

        if ($row.Type -eq "group") {
            Write-Host "  " -NoNewline
            Write-Host $row.Text -ForegroundColor $C_ACC
            continue
        }

        $isSelected = ($Selectable[$Pos] -eq $i)
        $pad   = [Math]::Max(1, $HintCol - 4 - $row.Text.Length)
        $trail = [Math]::Max(0, $w - 6 - $row.Text.Length - $pad - $row.Hint.Length)

        if ($isSelected) {
            Write-Host "  " -NoNewline
            Write-Host "> " -NoNewline -ForegroundColor $C_ACC
            Write-Host $row.Text -NoNewline -ForegroundColor $C_ACC
            Write-Host (" " * $pad) -NoNewline
            Write-Host $row.Hint -NoNewline -ForegroundColor $C_MUTE
            Write-Host (" " * $trail)
        } else {
            Write-Host "    " -NoNewline
            Write-Host $row.Text -NoNewline -ForegroundColor $C_TEXT
            Write-Host (" " * $pad) -NoNewline
            Write-Host $row.Hint -NoNewline -ForegroundColor $C_MUTE
            Write-Host (" " * $trail)
        }
    }

    Write-Host "  " -NoNewline
    Write-Host ("─" * ($w - 2)) -ForegroundColor $C_MUTE
    Write-Host "  " -NoNewline
    Write-Host "Up/Down" -NoNewline -ForegroundColor $C_ACC
    Write-Host " navigate   " -NoNewline -ForegroundColor $C_MUTE
    Write-Host "Enter" -NoNewline -ForegroundColor $C_ACC
    Write-Host " submit   " -NoNewline -ForegroundColor $C_MUTE
    Write-Host "q" -NoNewline -ForegroundColor $C_ACC
    Write-Host " quit" -ForegroundColor $C_MUTE
}

function Read-Menu {
    param([array]$Menu, [int[]]$Selectable)

    $pos = 0
    $prevCursor = [Console]::CursorVisible
    [Console]::CursorVisible = $false

    try {
        while ($true) {
            Clear-Host
            Write-MenuFrame -Menu $Menu -Selectable $Selectable -Pos $pos

            $wh = try { $Host.UI.RawUI.WindowSize.Height } catch { 40 }
            if ($wh -lt 30) {
                Write-Host ""
                Write-Host "  Window height $wh < 30. Enlarge window to avoid clipping." `
                    -ForegroundColor DarkYellow
            }

            $key = [Console]::ReadKey($true)

            switch ($key.Key) {
                'UpArrow'   { $pos = ($pos - 1 + $Selectable.Count) % $Selectable.Count }
                'DownArrow' { $pos = ($pos + 1) % $Selectable.Count }
                'Enter'     { return $Menu[$Selectable[$pos]].Key }
                'Escape'    { return "exit" }
                'Q'         { return "exit" }
            }
        }
    } finally {
        [Console]::CursorVisible = $prevCursor
    }
}

# ── Main loop ──────────────────────────────────────────────────────────────
Push-Location $root
try {
    :MainLoop while ($true) {
        $choice = Read-Menu -Menu $menu -Selectable $selectable

        switch ($choice) {
            "start"        {
                # The profiles are mandatory: without them compose starts only the base
                # infrastructure and `api` (behind docker-api) never comes up at all.
                Invoke-WithSpinner -Title "Starting stack..." -ArgumentList @($root, $envFile) -Action {
                    param($rootDir, $envFileArg)
                    Set-Location $rootDir
                    docker compose --env-file $envFileArg --profile docker-mcp --profile docker-api up -d --build
                }
            }
            "restart"      { Invoke-Compose up -d }
            "stop"         { Invoke-Compose down }
            "reset"        {
                if (gum confirm "Delete volumes? This is irreversible.") {
                    Invoke-Compose down -v
                }
            }
            "logs"         { Invoke-Compose logs -f }
            "logs-litellm" { Invoke-Compose logs -f litellm }
            "logs-api"     { Invoke-Compose logs -f api }
            "ps"           { Invoke-Compose ps }
            "health" {
                foreach ($ep in @(
                    @{ Name = "API";     Url = "http://localhost:8000/health" },
                    @{ Name = "LiteLLM"; Url = "http://localhost:4000/health/liveliness" }
                )) {
                    curl.exe -sf $ep.Url | Out-Null
                    if ($LASTEXITCODE -eq 0) {
                        Write-Host ("  {0,-10}  OK"   -f $ep.Name) -ForegroundColor $C_OK
                    } else {
                        Write-Host ("  {0,-10}  FAIL" -f $ep.Name) -ForegroundColor $C_ERR
                    }
                }
            }
            "validate" {
                Invoke-Compose config --quiet
                if ($LASTEXITCODE -eq 0) {
                    Write-Host "  OK    docker-compose.yml is valid" -ForegroundColor $C_OK
                } else {
                    Write-Host "  FAIL  docker-compose.yml is invalid" -ForegroundColor $C_ERR
                }
            }
            "models" {
                curl.exe -sf -H "Authorization: Bearer $masterKey" `
                    http://localhost:4000/v1/models | python -m json.tool
            }
            "test-tier" {
                $json = '{"model":"tier-mid","messages":[{"role":"user","content":"Say OK"}]}'
                curl.exe -sf http://localhost:4000/v1/chat/completions `
                    -H "Authorization: Bearer $masterKey" `
                    -H "Content-Type: application/json" `
                    -d $json | python -m json.tool
            }
            "migrate"      { Invoke-Compose exec api alembic upgrade head }
            "list-dbs"     { Invoke-Compose exec postgres psql -U postgres -c "\l" }
            "attach-up"    { Invoke-ComposeExtra "attachments" up -d clamav }
            "attach-s3-up" {
                # Preflight first: MinIO publishes no anonymously pullable image, so a raw
                # `up` fails with a registry error that reads like a broken compose file.
                python scripts/attachments_probe.py --preflight-image --skip-s3 --skip-clamav --skip-api
                if ($LASTEXITCODE -eq 0) {
                    Invoke-ComposeExtra "attachments-s3" up -d minio
                } else {
                    Write-Host ""
                    Write-Host "  S3 image is not pullable — fix ATTACHMENTS_MINIO_IMAGE (runbook §16.9)." `
                        -ForegroundColor $C_ERR
                    Write-Host "  Local dev needs no object store: ATTACHMENTS_BLOB_BACKEND=filesystem." `
                        -ForegroundColor $C_MUTE
                }
            }
            "attach-down"  { Invoke-ComposeAttachments stop clamav minio }
            "attach-probe" { python scripts/attachments_probe.py }
            "attach-logs-av" { Invoke-ComposeExtra "attachments" logs -f clamav }
            "attach-logs-s3" { Invoke-ComposeExtra "attachments-s3" logs -f minio }
            "shell"        { Invoke-Compose exec api sh }
            "swagger"      { Start-Process "http://localhost:8000/docs" }
            "litellm-ui"   { Start-Process "http://localhost:4000/ui" }
            "exit"         { break MainLoop }
        }

        if ($choice -ne "exit") {
            Write-Host ""
            Write-Host "  Press Enter to return..." -ForegroundColor $C_MUTE
            Read-Host | Out-Null
        }
    }
} finally {
    Pop-Location
    Write-Host ""
    Write-Host "  Session ended." -ForegroundColor $C_MUTE
}
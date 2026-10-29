# run.ps1
# Скрипт для управления проектом palatium-ai
# Использование: .\run.ps1 [-Command init|dev|staging|prod] [-Help]
# == == == == == == == == == == == == == == == == == == == == == == == == == == ==
# $PROFILE
# . $PROFILE
# notepad $PROFILE
# Алиасы для управления проектом palatium-ai
# function dev { & "D:\project\palatium-ai\run.ps1" dev }
# function staging { & "D:\project\palatium-ai\run.ps1" staging }
# function prod { & "D:\project\palatium-ai\run.ps1" prod }
# function init { & "D:\project\palatium-ai\run.ps1" init }
# function install-deps { & "D:\project\palatium-ai\run.ps1" install }

# # Дополнительно: быстрая справка
# function prj-help { & "D:\project\palatium-ai\run.ps1" help }
# == == == == == == == == == == == == == == == == == == == == == == == == == == ==

param(
    [string]$Command = "help"
)

# uv is the only dependency manager on dev (025): Poetry is legacy and is not kept in parallel.
$uvCmd = Get-Command uv -ErrorAction SilentlyContinue
if (-not $uvCmd) {
    Write-Host "uv not found. Install uv (https://docs.astral.sh/uv/) and re-run." -ForegroundColor Red
    exit 1
}
$Uv = $uvCmd.Source

function Show-Help {
    @"
Доступные команды:
  init         - Создать .env файлы из шаблона и синхронизировать зависимости (uv sync --frozen)
  install      - Синхронизировать зависимости (uv sync --frozen)
  dev          - Запустить приложение в режиме разработки
  staging      - Запустить приложение в режиме стейджинга
  prod         - Запустить приложение в режиме продакшена
  prj-help     - Показать эту справку
"@
}

function Init-Environment {
    Write-Host "🔧 Создание файлов окружения из шаблона..." -ForegroundColor Cyan
    if (-not (Test-Path "env/.env")) {
        Copy-Item "env/.env.example" "env/.env"
        Write-Host "  ✅ env/.env создан" -ForegroundColor Green
    } else {
        Write-Host "  ⚠️  env/.env уже существует" -ForegroundColor Yellow
    }
    if (-not (Test-Path "env/.env.dev")) {
        Copy-Item "env/.env.example" "env/.env.dev"
        Write-Host "  ✅ env/.env.dev создан" -ForegroundColor Green
    } else {
        Write-Host "  ⚠️  env/.env.dev уже существует" -ForegroundColor Yellow
    }
    if (-not (Test-Path "env/.env.staging")) {
        Copy-Item "env/.env.example" "env/.env.staging"
        Write-Host "  ✅ env/.env.staging создан" -ForegroundColor Green
    } else {
        Write-Host "  ⚠️  env/.env.staging уже существует" -ForegroundColor Yellow
    }
    if (-not (Test-Path "env/.env.prod")) {
        Copy-Item "env/.env.example" "env/.env.prod"
        Write-Host "  ✅ env/.env.prod создан" -ForegroundColor Green
    } else {
        Write-Host "  ⚠️  env/.env.prod уже существует" -ForegroundColor Yellow
    }
    Write-Host "📦 Установка зависимостей..." -ForegroundColor Cyan
    & $Uv sync --frozen
    if ($LASTEXITCODE -ne 0) {
        Write-Host "❌ uv sync --frozen failed (exit $LASTEXITCODE)." -ForegroundColor Red
        exit $LASTEXITCODE
    }
    Write-Host "✅ Готово! Отредактируйте файлы в env/ и заполните свои настройки." -ForegroundColor Green
}

function Install-Dependencies {
    Write-Host "📦 Установка зависимостей..." -ForegroundColor Cyan
    & $Uv sync --frozen
    if ($LASTEXITCODE -ne 0) {
        Write-Host "❌ uv sync --frozen failed (exit $LASTEXITCODE)." -ForegroundColor Red
        exit $LASTEXITCODE
    }
    Write-Host "✅ Зависимости установлены." -ForegroundColor Green
}

# `uv run` re-syncs on every start, and on Windows a failed hardlink makes uv re-copy the
# editable package each time (dev-up.ps1 pins UV_LINK_MODE for the same reason). The venv is
# created once here, then `--no-sync` keeps a launch to "start the app".
function Start-App {
    if (-not $env:UV_LINK_MODE) { $env:UV_LINK_MODE = "copy" }
    if (-not (Test-Path (Join-Path $PSScriptRoot ".venv"))) {
        & $Uv sync --frozen
        if ($LASTEXITCODE -ne 0) {
            Write-Host "❌ uv sync --frozen failed (exit $LASTEXITCODE) — run '.\run.ps1 install' first." -ForegroundColor Red
            exit $LASTEXITCODE
        }
    }
    & $Uv run --no-sync python -m palatium_ai.main
    exit $LASTEXITCODE
}

function Run-Dev {
    $env:ENV_FILE = "env/.env.dev"
    Start-App
}

function Run-Staging {
    $env:ENV_FILE = "env/.env.staging"
    Start-App
}

function Run-Prod {
    $env:ENV_FILE = "env/.env.prod"
    Start-App
}

# Основная логика
switch ($Command) {
    "init"      { Init-Environment }
    "install"   { Install-Dependencies }
    "dev"       { Run-Dev }
    "staging"   { Run-Staging }
    "prod"      { Run-Prod }
    "help"      { Show-Help }
    default     { Show-Help }
}
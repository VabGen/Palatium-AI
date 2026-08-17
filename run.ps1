# run.ps1
# Скрипт для управления проектом palatium-ai
# Использование: .\run.ps1 [-Command init|dev|staging|prod] [-Help]
# == == == == == == == == == == == == == == == == == == == == == == == == == == ==
# $PROFILE
# notepad $PROFILE
# . $PROFILE
# # Алиасы для управления проектом palatium-ai
# function dev   { .\run.ps1 dev }
# function staging { .\run.ps1 staging }
# function prod  { .\run.ps1 prod }
# function init  { .\run.ps1 init }
# function install-deps { .\run.ps1 install }
# 
# # Дополнительно: быстрая справка
# function prj-help { .\run.ps1 help }
# == == == == == == == == == == == == == == == == == == == == == == == == == == ==

param(
    [string]$Command = "help"
)

function Show-Help {
    @"
Доступные команды:
  init         - Создать .env файлы из шаблона и установить зависимости
  install      - Установить зависимости (poetry install --with dev)
  dev          - Запустить приложение в режиме разработки
  staging      - Запустить приложение в режиме стейджинга
  prod         - Запустить приложение в режиме продакшена
  help         - Показать эту справку
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
    poetry install --with dev
    Write-Host "✅ Готово! Отредактируйте файлы в env/ и заполните свои настройки." -ForegroundColor Green
}

function Install-Dependencies {
    Write-Host "📦 Установка зависимостей..." -ForegroundColor Cyan
    poetry install --with dev
    Write-Host "✅ Зависимости установлены." -ForegroundColor Green
}

function Run-Dev {
    $env:ENV_FILE = "env/.env.dev"
    poetry run python -m palatium_ai.main
}

function Run-Staging {
    $env:ENV_FILE = "env/.env.staging"
    poetry run python -m palatium_ai.main
}

function Run-Prod {
    $env:ENV_FILE = "env/.env.prod"
    poetry run python -m palatium_ai.main
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
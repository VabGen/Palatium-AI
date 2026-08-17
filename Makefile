# ==============================================================================
# Makefile для palatium-ai
# Управление окружением и запуск приложения
# choco install make -y
# ==============================================================================

.PHONY: help init install dev staging prod

# ------------------------------------------------------------------------------
# Справка
# ------------------------------------------------------------------------------
help:
	@echo "Доступные команды:"
	@echo "  make init         - Создать .env файлы из шаблона (не перезаписывает существующие)"
	@echo "  make install      - Установить зависимости (poetry install --with dev)"
	@echo "  make dev          - Запустить приложение в режиме разработки"
	@echo "  make staging      - Запустить приложение в режиме стейджинга"
	@echo "  make prod         - Запустить приложение в режиме продакшена"

# ------------------------------------------------------------------------------
# Инициализация окружения
# ------------------------------------------------------------------------------
init:
	@echo "🔧 Создание файлов окружения из шаблона..."
	@if [ ! -f env/.env ]; then cp env/.env.example env/.env && echo "  ✅ env/.env"; else echo "  ⚠️  env/.env уже существует"; fi
	@if [ ! -f env/.env.dev ]; then cp env/.env.example env/.env.dev && echo "  ✅ env/.env.dev"; else echo "  ⚠️  env/.env.dev уже существует"; fi
	@if [ ! -f env/.env.staging ]; then cp env/.env.example env/.env.staging && echo "  ✅ env/.env.staging"; else echo "  ⚠️  env/.env.staging уже существует"; fi
	@if [ ! -f env/.env.prod ]; then cp env/.env.example env/.env.prod && echo "  ✅ env/.env.prod"; else echo "  ⚠️  env/.env.prod уже существует"; fi
	@echo "📦 Установка зависимостей..."
	@poetry install --with dev
	@echo "✅ Готово! Отредактируйте файлы в env/ и заполните свои настройки."

# ------------------------------------------------------------------------------
# Установка зависимостей (отдельно)
# ------------------------------------------------------------------------------
install:
	@echo "📦 Установка зависимостей..."
	@poetry install --with dev
	@echo "✅ Зависимости установлены."

# ------------------------------------------------------------------------------
# Запуск приложения в разных окружениях
# ------------------------------------------------------------------------------
dev:
	@ENV_FILE=env/.env.dev poetry run python -m palatium_ai.main

staging:
	@ENV_FILE=env/.env.staging poetry run python -m palatium_ai.main

prod:
	@ENV_FILE=env/.env.prod poetry run python -m palatium_ai.main
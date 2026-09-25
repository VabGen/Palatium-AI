# ==============================================================================
# Makefile для palatium-ai
# Linux / macOS / WSL. На Windows используйте .\scripts\menu.ps1
#
# Установка make:
#   macOS:  brew install make
#   Linux:  sudo apt install make
#   Windows: choco install make -y
# ==============================================================================

ENV_FILE ?= env/.env
COMPOSE  := docker compose --env-file $(ENV_FILE)

.PHONY: help menu init install dev staging prod \
        up down reset ps logs logs-litellm logs-api \
        verify migrate shell list-dbs models test-tier \
        validate swagger litellm-ui

# ------------------------------------------------------------------------------
# Справка / меню
# ------------------------------------------------------------------------------
help:
	@echo "Palatium-AI — доступные команды:"
	@echo ""
	@echo "  ── Управление стеком ──"
	@echo "  make up          — поднять стек (build)"
	@echo "  make down        — остановить"
	@echo "  make reset       — остановить + удалить volumes"
	@echo "  make ps          — статус сервисов"
	@echo "  make logs        — логи всех"
	@echo "  make logs-litellm — логи LiteLLM"
	@echo "  make logs-api    — логи API"
	@echo ""
	@echo "  ── Проверки ──"
	@echo "  make verify      — health всех endpoints"
	@echo "  make models      — список моделей LiteLLM"
	@echo "  make test-tier   — тестовый запрос tier-mid"
	@echo "  make validate    — валидация docker-compose.yml"
	@echo "  make list-dbs    — список БД Postgres"
	@echo ""
	@echo "  ── Разработка ──"
	@echo "  make init        — создать .env из шаблона"
	@echo "  make install     — poetry install --with dev"
	@echo "  make dev         — запуск локально (env/.env.dev)"
	@echo "  make staging     — запуск локально (env/.env.staging)"
	@echo "  make prod        — запуск локально (env/.env.prod)"
	@echo "  make migrate     — alembic upgrade head"
	@echo "  make shell       — shell в контейнере api"
	@echo ""
	@echo "  ── UI ──"
	@echo "  make swagger     — открыть Swagger UI"
	@echo "  make litellm-ui  — открыть LiteLLM UI"

# ------------------------------------------------------------------------------
# Инициализация окружения
# ------------------------------------------------------------------------------
init:
	@echo "🔧 Создание файлов окружения из шаблона..."
	@[ -f env/.env ]          || (cp env/.env.example env/.env          && echo "  ✅ env/.env")
	@[ -f env/.env.dev ]      || (cp env/.env.example env/.env.dev      && echo "  ✅ env/.env.dev")
	@[ -f env/.env.staging ]  || (cp env/.env.example env/.env.staging  && echo "  ✅ env/.env.staging")
	@[ -f env/.env.prod ]     || (cp env/.env.example env/.env.prod     && echo "  ✅ env/.env.prod")
	@echo "📦 Установка зависимостей..."
	@poetry install --with dev
	@echo "✅ Готово! Отредактируйте файлы в env/."

install:
	@echo "📦 Установка зависимостей..."
	@poetry install --with dev
	@echo "✅ Зависимости установлены."

# ------------------------------------------------------------------------------
# Управление стеком
# ------------------------------------------------------------------------------
up:
	$(COMPOSE) up -d --build
	@echo "✓ Стек поднят. Swagger: http://localhost:8000/docs"

down:
	$(COMPOSE) down

reset:
	$(COMPOSE) down -v
	@echo "✓ Volumes удалены"

ps:
	$(COMPOSE) ps

logs:
	$(COMPOSE) logs -f

logs-litellm:
	$(COMPOSE) logs -f litellm

logs-api:
	$(COMPOSE) logs -f api

# ------------------------------------------------------------------------------
# Проверки
# ------------------------------------------------------------------------------
verify:
	@echo "→ API health..." && curl -sf http://localhost:8000/health && echo " ✅" || echo " ❌"
	@echo "→ LiteLLM liveness..." && curl -sf http://localhost:4000/health/liveliness && echo " ✅" || echo " ❌"
	@echo "→ MCP EDMS..." && curl -sf http://localhost:8080/health && echo " ✅" || echo " ❌"
	@echo "→ MCP Analytics..." && curl -sf http://localhost:8081/health && echo " ✅" || echo " ❌"

models:
	@curl -sf -H "Authorization: Bearer sk-palatium-master" \
		http://localhost:4000/v1/models | python -m json.tool

test-tier:
	@curl -sf http://localhost:4000/v1/chat/completions \
		-H "Authorization: Bearer sk-palatium-master" \
		-H "Content-Type: application/json" \
		-d '{"model":"tier-mid","messages":[{"role":"user","content":"Say OK"}]}' \
		| python -m json.tool

validate:
	$(COMPOSE) config --quiet && echo "✅ docker-compose.yml валиден"
	@$(COMPOSE) config | grep -E "TIER_" || true

list-dbs:
	$(COMPOSE) exec postgres psql -U postgres -c "\l"
	@echo "--- Расширения postgres ---"
	$(COMPOSE) exec postgres psql -U postgres -d postgres -c "\dx"

# ------------------------------------------------------------------------------
# Разработка (локальный Poetry)
# ------------------------------------------------------------------------------
dev:
	@ENV_FILE=env/.env.dev poetry run python -m palatium_ai.main

staging:
	@ENV_FILE=env/.env.staging poetry run python -m palatium_ai.main

prod:
	@ENV_FILE=env/.env.prod poetry run python -m palatium_ai.main

migrate:
	$(COMPOSE) exec api alembic upgrade head

shell:
	$(COMPOSE) exec api sh

# ------------------------------------------------------------------------------
# UI
# ------------------------------------------------------------------------------
swagger:
	@python -c "import webbrowser; webbrowser.open('http://localhost:8000/docs')"

litellm-ui:
	@python -c "import webbrowser; webbrowser.open('http://localhost:4000/ui')"
# ==============================================================================
# Palatium-AI — единая точка входа.
# palatium-menu
# Кросс-платформенный: Linux, macOS, WSL, Git Bash, Windows (scoop install make).
# ==============================================================================

ENV_FILE ?= env/.env
COMPOSE  := docker compose --env-file $(ENV_FILE) --profile docker-mcp --profile docker-api
# ^ профили обязательны: api.depends_on ссылается на mcp-edms/mcp-analytics.

LITELLM_MASTER_KEY ?= $(shell grep -E '^LITELLM_MASTER_KEY=' $(ENV_FILE) 2>/dev/null \
                         | head -n1 | cut -d= -f2- | tr -d '"' | tr -d "'")

.DEFAULT_GOAL := help
.PHONY: help init install up down reset ps logs logs-api logs-litellm \
        verify require-key models test-tier validate list-dbs migrate shell \
        swagger litellm-ui attach-build attach-up attach-down attach-s3-up \
        attach-s3-down attach-probe

# ──────────────────────────────────────────────────────────────────────────────
help:  ## Показать эту справку
	@awk 'BEGIN{FS=":.*##"; printf "\nPalatium-AI — команды:\n\n"} \
	     /^[a-zA-Z_-]+:.*##/ {printf "  make %-15s %s\n", $$1, $$2}' $(MAKEFILE_LIST)
	@echo ""

# ──────────────────────────────────────────────────────────────────────────────
# Стек
# ──────────────────────────────────────────────────────────────────────────────
init: ## Создать env/.env из шаблона + poetry install
	@[ -f $(ENV_FILE) ] || (cp env/.env.example $(ENV_FILE) && echo "✅ $(ENV_FILE)")
	@poetry install --with dev

install: ## poetry install --with dev
	@poetry install --with dev

up: ## Поднять весь стек
	$(COMPOSE) up -d --build
	@echo "✓ http://localhost:8000/docs"

down: ## Остановить
	$(COMPOSE) down

reset: ## Остановить + удалить volumes (DESTRUCTIVE)
	$(COMPOSE) down -v

ps: ## Статус сервисов
	$(COMPOSE) ps

logs: ## Логи всех (Ctrl+C для выхода)
	$(COMPOSE) logs -f

logs-api: ## Логи api
	$(COMPOSE) logs -f api

logs-litellm: ## Логи litellm
	$(COMPOSE) logs -f litellm

# ──────────────────────────────────────────────────────────────────────────────
# Проверки
# ──────────────────────────────────────────────────────────────────────────────
verify: ## Health всех endpoints
	@curl -sf http://localhost:8000/health && echo " ✅ API" || echo " ❌ API"
	@curl -sf http://localhost:4000/health/liveliness && echo " ✅ LiteLLM" || echo " ❌ LiteLLM"
	@curl -sf http://localhost:8080/health && echo " ✅ MCP EDMS" || echo " ❌ MCP EDMS"
	@curl -sf http://localhost:8081/health && echo " ✅ MCP Analytics" || echo " ❌ MCP Analytics"

require-key:
	@[ -n "$(LITELLM_MASTER_KEY)" ] || { echo "❌ LITELLM_MASTER_KEY not set in $(ENV_FILE)"; exit 1; }

models: require-key ## Список tier-моделей LiteLLM
	@curl -sf -H "Authorization: Bearer $(LITELLM_MASTER_KEY)" \
		http://localhost:4000/v1/models | python -m json.tool

test-tier: require-key ## Тестовый запрос через tier-mid
	@curl -sf http://localhost:4000/v1/chat/completions \
		-H "Authorization: Bearer $(LITELLM_MASTER_KEY)" \
		-H "Content-Type: application/json" \
		-d '{"model":"tier-mid","messages":[{"role":"user","content":"Say OK"}]}' \
		| python -m json.tool

validate: ## Валидация docker-compose.yml
	$(COMPOSE) config --quiet && echo "✅ docker-compose.yml валиден"

list-dbs: ## Список БД + расширений Postgres
	$(COMPOSE) exec postgres psql -U postgres -c "\l"
	$(COMPOSE) exec postgres psql -U postgres -d postgres -c "\dx"

migrate: ## Alembic upgrade head
	$(COMPOSE) exec api alembic upgrade head

shell: ## Shell в контейнере api
	$(COMPOSE) exec api sh

# ──────────────────────────────────────────────────────────────────────────────
# Вложения (attachments): AV-движок и S3-хранилище — оба опциональны
# ──────────────────────────────────────────────────────────────────────────────
attach-build: ## Собрать api с extras attachments (minio/pypdf/python-docx)
	$(COMPOSE) build --build-arg WITH_ATTACHMENTS=1 api

attach-up: ## Поднять AV-движок clamd (профиль attachments)
	$(COMPOSE) --profile attachments up -d clamav

attach-down: ## Остановить AV и S3 (данные и volumes сохраняются)
	$(COMPOSE) --profile attachments --profile attachments-s3 stop clamav minio

# Preflight ОБЯЗАТЕЛЕН: upstream-образы MinIO больше нигде не отдаются анонимно
# (Docker Hub 404 / quay.io 401 / ghcr.io 403). Без проверки `up` падает ошибкой
# авторизации реестра, которую легко принять за битый compose (см. runbook §16.9).
attach-s3-up: ## Поднять S3-хранилище minio (профиль attachments-s3) + preflight образа
	python scripts/attachments_probe.py --preflight-image --skip-s3 --skip-clamav --skip-api
	$(COMPOSE) --profile attachments-s3 up -d minio

attach-s3-down: ## Остановить S3 (volume palatium_minio_data сохраняется)
	$(COMPOSE) --profile attachments-s3 stop minio

attach-probe: ## Диагностика вложений: API + clamd + S3 (что именно лежит)
	python scripts/attachments_probe.py

# ──────────────────────────────────────────────────────────────────────────────
# UI
# ──────────────────────────────────────────────────────────────────────────────
swagger: ## Открыть Swagger UI
	@python -c "import webbrowser; webbrowser.open('http://localhost:8000/docs')"

litellm-ui: ## Открыть LiteLLM UI
	@python -c "import webbrowser; webbrowser.open('http://localhost:4000/ui')"
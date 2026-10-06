# ==============================================================================
# Palatium-AI — единая точка входа.
# palatium-menu
# Кросс-платформенный: Linux, macOS, WSL, Git Bash, Windows (scoop install make).
# ==============================================================================

ENV_FILE ?= env/.env
# `?=` alone is not enough: it treats a *defined but empty* environment variable as a
# deliberate override. An exported `ENV_FILE=` then silently drops `--env-file` from every
# recipe, and compose fails on the first `:?` secret with a misleading message. Normalise it.
ifeq ($(strip $(ENV_FILE)),)
ENV_FILE := env/.env
endif

COMPOSE  := docker compose --env-file $(ENV_FILE) --profile docker-mcp --profile docker-api
# ^ профили обязательны: api.depends_on ссылается на mcp-edms/mcp-analytics.

# Profiles + overlays for the attachment stack, computed by the probe (010): it also
# decides whether `attachments-s3` can be added, from the store image's availability.
# These belong to the *default* launch, not to an extra "full" one — env/.env sets
# ATTACHMENTS_BLOB_BACKEND=minio, and `ensure_bucket()` aborts the API boot when the
# store is missing (application/wiring.py), so a plain `up` without them would crash-loop.
# `=` (recursive, not `:=`) on purpose: python runs when a recipe uses it, not on `make help`.
# It also stays off the path of `ps`/`logs`/`shell` — `--compose-args` runs `docker manifest
# inspect`, so only the targets that create or recreate api/mcp may expand it. Recreating the
# api container *without* the overlays silently downgrades it to the dev backends from
# env/.env (scanner disabled, filesystem blob), which is pinned by
# tests/unit/test_make_helpers.py::test_every_api_recreating_target_loads_the_attachment_overlays.
FULL_FLAGS = $(shell python scripts/attachments_probe.py --compose-args)

# No POSIX tools on the critical path: `grep`/`cut`/`tr` are absent from a stock Windows
# PATH, which made this empty and `require-key` refuse `models`/`test-tier` (see make_helpers).
LITELLM_MASTER_KEY ?= $(shell python scripts/make_helpers.py env-get LITELLM_MASTER_KEY --env-file $(ENV_FILE))

.DEFAULT_GOAL := help
.PHONY: help init install up up-full rebuild-app obs-up obs-down down reset ps logs \
        logs-api logs-litellm verify require-key models test-tier validate list-dbs \
        migrate shell swagger litellm-ui attach-build attach-up attach-down \
        attach-s3-up attach-s3-down attach-probe perf

# ──────────────────────────────────────────────────────────────────────────────
help:  ## Показать эту справку
	@python scripts/make_helpers.py help

# ──────────────────────────────────────────────────────────────────────────────
# Стек
# ──────────────────────────────────────────────────────────────────────────────
init: ## Создать env/.env из шаблона + poetry install
	@python scripts/make_helpers.py init-env --env-file $(ENV_FILE)
	@poetry install --with dev

install: ## poetry install --with dev
	@poetry install --with dev

# `--wait` on the probe, not on compose: `docker compose up --wait` treats the one-shot
# `silo-init` container (creates the buckets, exits 0) as a failure, so it rejected a
# perfectly healthy launch. Readiness is decided by the checks below, which retry only
# what is not answering yet — clamd needs up to 5 min to load its signatures, and
# `make up` used to print "FAIL clamav" for a stack that was working as designed.
up: ## Собрать и запустить всё, КРОМЕ observability (API + MCP + AV + S3)
	docker compose --env-file $(ENV_FILE) $(FULL_FLAGS) up -d --build
	@python scripts/attachments_probe.py --mode --full --env-file $(ENV_FILE)
	@python scripts/attachments_probe.py --wait 420 --env-file $(ENV_FILE)
	@echo "✓ http://localhost:8000/docs"

up-full: ## Собрать и запустить ВЕСЬ стек, включая observability (Langfuse v3 + ClickHouse)
	@echo "  note: observability peak (clickhouse 2048 + langfuse-web 768 + worker 512) does not"
	@echo "        fit the default Docker VM (~7.7 GiB) — raise it in %USERPROFILE%\.wslconfig"
	@echo "        (memory=12GB) and restart Docker Desktop first, or the OOM killer will fire."
	docker compose --env-file $(ENV_FILE) --profile observability $(FULL_FLAGS) up -d --build
	@python scripts/attachments_probe.py --mode --full --env-file $(ENV_FILE)
	@python scripts/attachments_probe.py --wait 420 --env-file $(ENV_FILE)
	@echo "✓ API http://localhost:8000/docs · Langfuse http://localhost:3000"

# Readiness BEFORE `verify`: a fresh api needs ~60 s (entrypoint alembic + uvicorn
# bootstrap) and `verify` has no retry of its own. Running it first printed
# "API FAIL / LiteLLM FAIL" on a healthy recreate — and because make stops at the first
# non-zero exit, the recipe aborted *before* the probes that do wait could retry. The
# waiting probe is the only step here that can turn a cold start into a truthful verdict.
rebuild-app: ## Пересобрать и перезапустить ТОЛЬКО api + MCP-серверы (инфра не трогается)
	docker compose --env-file $(ENV_FILE) $(FULL_FLAGS) build api mcp-edms mcp-analytics
	docker compose --env-file $(ENV_FILE) $(FULL_FLAGS) up -d --no-deps api mcp-edms mcp-analytics
	@python scripts/attachments_probe.py --mode --full --env-file $(ENV_FILE)
	@python scripts/attachments_probe.py --skip-s3 --wait 120 --env-file $(ENV_FILE)
	@python scripts/make_helpers.py verify
	@echo "✓ api + mcp-edms + mcp-analytics пересобраны и перезапущены"

obs-up: ## Поднять observability (Langfuse v3 + ClickHouse + worker + store)
	docker compose --env-file $(ENV_FILE) --profile observability up -d minio silo-init clickhouse langfuse-web langfuse-worker
	@echo "✓ Langfuse http://localhost:3000"

obs-down: ## Остановить observability (store minio не трогаем — он общий с вложениями)
	docker compose --env-file $(ENV_FILE) --profile observability stop langfuse-web langfuse-worker clickhouse

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
verify: ## Health всех endpoints (exit != 0, если что-то лежит)
	@python scripts/make_helpers.py verify

require-key:
	@python scripts/make_helpers.py require-key LITELLM_MASTER_KEY --env-file $(ENV_FILE)

models: require-key ## Список tier-моделей LiteLLM
	@python scripts/make_helpers.py models --env-file $(ENV_FILE)

test-tier: require-key ## Тестовый запрос через tier-mid
	@python scripts/make_helpers.py chat --model tier-mid --env-file $(ENV_FILE)

validate: ## Валидация docker-compose.yml
	$(COMPOSE) config --quiet && echo "✅ docker-compose.yml валиден"

perf: ## Нагрузочные тесты сложности hot-path (маркер slow; вне PR-CI, 080)
	@poetry run pytest tests/perf -q -m slow

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
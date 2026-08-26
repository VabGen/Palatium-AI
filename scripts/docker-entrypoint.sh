#!/bin/sh
# scripts/docker-entrypoint.sh — PID-friendly entrypoint for palatium-ai runtime.
# Invoked via: tini -- sh /app/scripts/docker-entrypoint.sh <cmd...>
set -eu

HOST="${UVICORN_HOST:-0.0.0.0}"
PORT="${UVICORN_PORT:-8000}"
WORKERS="${UVICORN_WORKERS:-1}"
# Не трогаем LOG_LEVEL (Pydantic Literal: DEBUG|INFO|...) — только копия для uvicorn.
UVICORN_LOG_LEVEL="$(printf '%s' "${LOG_LEVEL:-INFO}" | tr '[:upper:]' '[:lower:]')"

if [ "${RUN_MIGRATIONS:-0}" = "1" ] || [ "${RUN_MIGRATIONS:-false}" = "true" ]; then
  echo "[entrypoint] RUN_MIGRATIONS=1 → ensure schema + alembic upgrade head"
  python -c "import asyncio; from palatium_ai.core.config import get_settings; from palatium_ai.infrastructure.database import ensure_database_and_schema; asyncio.run(ensure_database_and_schema(get_settings()))"
  alembic upgrade head
fi

# Default CMD is literal "uvicorn" → expand to full server command.
if [ "$#" -eq 0 ] || [ "$1" = "uvicorn" ]; then
  if [ "$#" -gt 0 ] && [ "$1" = "uvicorn" ]; then
    shift
  fi
  if [ "$#" -eq 0 ]; then
    set -- \
      uvicorn "palatium_ai.main:app" \
      --host "${HOST}" \
      --port "${PORT}" \
      --workers "${WORKERS}" \
      --proxy-headers \
      --forwarded-allow-ips="*" \
      --timeout-keep-alive 30 \
      --log-level "${UVICORN_LOG_LEVEL}"
  else
    set -- uvicorn "$@"
  fi
fi

echo "[entrypoint] exec: $*"
exec "$@"

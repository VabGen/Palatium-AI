#!/usr/bin/env bash
# Пример: вытянуть секреты из HashiCorp Vault и экспортировать в env.
# Не коммитить с реальным VAULT_TOKEN.
#
# Требования: vault CLI, jq
#   export VAULT_ADDR=https://vault.example.com
#   export VAULT_TOKEN=...
#   source scripts/load-secrets-from-vault.example.sh staging
#   ENV_FILE=env/.env.staging poetry run python -m palatium_ai.main

set -euo pipefail

ENV_NAME="${1:-staging}"
PREFIX="secret/palatium/${ENV_NAME}"

if ! command -v vault >/dev/null 2>&1; then
  echo "vault CLI не найден" >&2
  exit 1
fi

export POSTGRES_PASSWORD
POSTGRES_PASSWORD="$(vault kv get -field=password "${PREFIX}/postgres")"

export OLLAMA_API_KEY
OLLAMA_API_KEY="$(vault kv get -field=api_key "${PREFIX}/ollama")"

if vault kv get -field=api_key "${PREFIX}/langchain" >/dev/null 2>&1; then
  export LANGCHAIN_API_KEY
  LANGCHAIN_API_KEY="$(vault kv get -field=api_key "${PREFIX}/langchain")"
fi

echo "Секреты для '${ENV_NAME}' загружены в текущую shell-сессию (не логируются)."

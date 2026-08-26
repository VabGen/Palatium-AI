#!/usr/bin/env bash
# afterFileEdit — на изменённых .py файлах прогоняет ruff + mypy --strict,
# результат пишет в лог, который агент видит в Hooks output channel.

set -euo pipefail
INPUT="$(cat)"
FILE_PATH="$(echo "$INPUT" | jq -r '.file_path // ""')"

if [[ "$FILE_PATH" != *.py ]]; then
  exit 0
fi

# Skip generated / cache paths.
case "$FILE_PATH" in
  *"/__pycache__/"*|*".mypy_cache"*|*".ruff_cache"*|*"/migrations/"*)
    exit 0
    ;;
esac

STATUS=0

if command -v poetry >/dev/null 2>&1; then
  if ! poetry run ruff check --fix "$FILE_PATH"; then
    echo "❌ ruff failed for $FILE_PATH" >&2
    STATUS=1
  fi
  if ! poetry run mypy --strict "$FILE_PATH"; then
    echo "❌ mypy --strict failed for $FILE_PATH — см. 010-typing-strict.mdc" >&2
    STATUS=1
  fi
elif command -v ruff >/dev/null 2>&1; then
  if ! ruff check --fix "$FILE_PATH"; then
    echo "❌ ruff failed for $FILE_PATH" >&2
    STATUS=1
  fi
  if command -v mypy >/dev/null 2>&1; then
    if ! mypy --strict "$FILE_PATH"; then
      echo "❌ mypy --strict failed for $FILE_PATH — см. 010-typing-strict.mdc" >&2
      STATUS=1
    fi
  fi
fi

exit "$STATUS"

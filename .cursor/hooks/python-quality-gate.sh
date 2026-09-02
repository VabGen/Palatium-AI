#!/usr/bin/env bash
# afterFileEdit — на изменённых .py файлах прогоняет ruff + mypy --strict,
# результат пишет в лог, который агент видит в Hooks output channel.

set -euo pipefail
INPUT="$(cat)"
if command -v jq >/dev/null 2>&1; then
  FILE_PATH="$(echo "$INPUT" | jq -r '.file_path // ""')"
else
  echo "⚠️  python-quality-gate: jq не найден — извлекаю file_path через python3." >&2
  FILE_PATH="$(printf '%s' "$INPUT" | python3 -c "import sys,json; print(json.load(sys.stdin).get('file_path') or '')" 2>/dev/null || true)"
fi

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
RAN_ANYTHING=0

if command -v poetry >/dev/null 2>&1; then
  RAN_ANYTHING=1
  if ! poetry run ruff check --fix "$FILE_PATH"; then
    echo "❌ ruff failed for $FILE_PATH" >&2
    STATUS=1
  fi
  if ! poetry run mypy --strict "$FILE_PATH"; then
    echo "❌ mypy --strict failed for $FILE_PATH — см. 010-typing-strict.mdc" >&2
    STATUS=1
  fi
elif command -v ruff >/dev/null 2>&1; then
  RAN_ANYTHING=1
  if ! ruff check --fix "$FILE_PATH"; then
    echo "❌ ruff failed for $FILE_PATH" >&2
    STATUS=1
  fi
  if command -v mypy >/dev/null 2>&1; then
    if ! mypy --strict "$FILE_PATH"; then
      echo "❌ mypy --strict failed for $FILE_PATH — см. 010-typing-strict.mdc" >&2
      STATUS=1
    fi
  else
    echo "⚠️  mypy не найден в PATH — .py файл изменён БЕЗ проверки типов ($FILE_PATH)." >&2
  fi
fi

if [[ "$RAN_ANYTHING" -eq 0 ]]; then
  echo "⚠️  Ни poetry, ни ruff не найдены в PATH — quality-gate НЕ запускался для $FILE_PATH." >&2
fi

exit "$STATUS"

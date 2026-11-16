#!/usr/bin/env bash
# beforeShellExecution — DEPRECATED STUB.

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

# uv предпочтителен (025: единственный менеджер зависимостей); python/python3 — аварийный
# путь для машины без uv. Нет ни одного — fail-closed: молча пропустить проверку нельзя (020).
if command -v uv >/dev/null 2>&1; then
  exec uv run --no-project python "$SCRIPT_DIR/deny-dangerous-shell.py"
fi

if ! command -v python >/dev/null 2>&1 && ! command -v python3 >/dev/null 2>&1; then
  echo '{"permission":"deny","agentMessage":"deny-dangerous-shell.sh: ни uv, ни python не найдены — канонический guard не может выполниться, fail-closed (020).","userMessage":"Команда заблокирована: guard безопасности недоступен."}'
  exit 0
fi

PY="$(command -v python || command -v python3)"
exec "$PY" "$SCRIPT_DIR/deny-dangerous-shell.py"

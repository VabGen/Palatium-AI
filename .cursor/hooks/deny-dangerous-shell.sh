#!/usr/bin/env bash
# beforeShellExecution — DEPRECATED STUB.

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

if ! command -v python >/dev/null 2>&1 && ! command -v python3 >/dev/null 2>&1; then
  echo '{"permission":"deny","agentMessage":"deny-dangerous-shell.sh: python недоступен, канонический guard не может выполниться — fail-closed (020).","userMessage":"Команда заблокирована: guard безопасности недоступен."}'
  exit 0
fi

PY="$(command -v python || command -v python3)"
exec "$PY" "$SCRIPT_DIR/deny-dangerous-shell.py"

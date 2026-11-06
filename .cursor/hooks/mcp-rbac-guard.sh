#!/usr/bin/env bash
# beforeMCPExecution — тонкая обёртка над mcp-rbac-guard.py (быстрый hot-path).
# Логика SoT — в .py; bash только выбирает интерпретатор (timeout хука = 10с).

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
GUARD_PY="$SCRIPT_DIR/mcp-rbac-guard.py"

_run_py() {
  if command -v python >/dev/null 2>&1; then
    python "$GUARD_PY"
    return $?
  fi
  if command -v python3 >/dev/null 2>&1; then
    python3 "$GUARD_PY"
    return $?
  fi
  if command -v uv >/dev/null 2>&1; then
    uv run --no-project python "$GUARD_PY"
    return $?
  fi
  return 127
}

if ! _run_py; then
  printf '{"permission":"deny","agentMessage":"mcp-rbac-guard: python/uv недоступен — fail-closed (020).","userMessage":"Вызов MCP-инструмента заблокирован: guard безопасности недоступен."}'
fi
exit 0

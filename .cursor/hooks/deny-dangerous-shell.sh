#!/usr/bin/env bash
# beforeShellExecution — блокирует деструктивные/опасные команды.
# Читает JSON из stdin; пишет JSON permission в stdout.
# Без зависимости от jq (Windows / Git Bash): парсинг через Python.

set -euo pipefail
INPUT="$(cat)"

extract_command() {
  if command -v jq >/dev/null 2>&1; then
    echo "$INPUT" | jq -r '.command // ""'
    return
  fi
  printf '%s' "$INPUT" | python -c "import sys,json; print(json.load(sys.stdin).get('command') or '')"
}

emit_json() {
  local payload="$1"
  if command -v jq >/dev/null 2>&1; then
    echo "$payload"
    return
  fi
  printf '%s\n' "$payload"
}

CMD="$(extract_command)"

DENY_PATTERNS=(
  'rm[[:space:]]+-rf[[:space:]]+/'
  'git[[:space:]]+push[[:space:]]+--force[[:space:]]+.*(main|master|prod)'
  'curl[[:space:]].*\|[[:space:]]*bash'
  'wget[[:space:]].*\|[[:space:]]*sh'
  ':(){ :\|:& };:'
  'DROP[[:space:]]+TABLE'
  'DROP[[:space:]]+DATABASE'
)

for pattern in "${DENY_PATTERNS[@]}"; do
  if echo "$CMD" | grep -Eiq "$pattern"; then
    python -c "import json,sys; print(json.dumps({'permission':'deny','agentMessage':'Команда заблокирована политикой ZeroTrust Agent Platform (деструктивная/опасная операция).','userMessage':'Заблокирована потенциально опасная команда: '+sys.argv[1]}))" "$CMD"
    exit 0
  fi
done

python -c "import json; print(json.dumps({'permission':'allow'}))"

#!/usr/bin/env bash
# afterFileEdit — сканирует изменённый файл на утечку секретов.
# stdin JSON: { file_path, old_content, new_content, hook_event_name, ... }
# Не может "deny" (событие уже произошло) — логирует и предупреждает агента.

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=lib/audit-chain.sh
source "$SCRIPT_DIR/lib/audit-chain.sh"

INPUT="$(cat)"

# Не failClosed-хук (afterFileEdit) — при отсутствии jq не молчим и не падаем,
# а деградируем на python3-фолбэк для извлечения полей (audit-chain при этом
# всё равно пропустится: он сам требует jq и явно предупредит в stderr).
if command -v jq >/dev/null 2>&1; then
  FILE_PATH="$(echo "$INPUT" | jq -r '.file_path // ""')"
  NEW_CONTENT="$(echo "$INPUT" | jq -r '.new_content // ""')"
else
  echo "⚠️  secret-scan: jq не найден — извлекаю поля через python3 (audit-chain запись будет пропущена)." >&2
  FILE_PATH="$(printf '%s' "$INPUT" | python3 -c "import sys,json; print(json.load(sys.stdin).get('file_path') or '')" 2>/dev/null || true)"
  NEW_CONTENT="$(printf '%s' "$INPUT" | python3 -c "import sys,json; print(json.load(sys.stdin).get('new_content') or '')" 2>/dev/null || true)"
fi

LOG_DIR="$SCRIPT_DIR/../logs"
mkdir -p "$LOG_DIR"

# name:pattern — имя нужно для audit-события и для читаемого сообщения.
SECRET_PATTERNS=(
  "openai_or_anthropic_key:sk-[a-zA-Z0-9]{20,}"
  "aws_access_key:AKIA[0-9A-Z]{16}"
  "private_key_block:-----BEGIN (RSA|EC|OPENSSH) PRIVATE KEY-----"
  "password_literal:password[[:space:]]*[:=][[:space:]]*[\"'][^\"'[:space:]]{4,}[\"']"
  "anthropic_api_key_env:ANTHROPIC_API_KEY[[:space:]]*[:=][[:space:]]*[^[:space:]]{4,}"
  "mcp_auth_token_env:MCP_AUTH_TOKEN[[:space:]]*[:=][[:space:]]*[^[:space:]]{8,}"
  "bearer_token:Bearer[[:space:]]+[A-Za-z0-9._-]{24,}"
)

for entry in "${SECRET_PATTERNS[@]}"; do
  name="${entry%%:*}"
  pattern="${entry#*:}"
  if echo "$NEW_CONTENT" | grep -Eiq -- "$pattern"; then
    echo "[$(date -u +%FT%TZ)] SECRET_PATTERN_MATCH pattern=$name file=$FILE_PATH" >> "$LOG_DIR/security-events.log"
    audit_append_event "secret_pattern_match" "pattern" "$name" "file_path" "$FILE_PATH" || true
    echo "⚠️  Обнаружен потенциальный секрет ($name) в $FILE_PATH — проверь перед коммитом." >&2
    break
  fi
done

# afterFileEdit не блокирует — только наблюдательный хук.
exit 0

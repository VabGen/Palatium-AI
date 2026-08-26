#!/usr/bin/env bash
# afterFileEdit — сканирует изменённый файл на утечку секретов.
# stdin JSON: { file_path, old_content, new_content, hook_event_name, ... }
# Не может "deny" (событие уже произошло) — логирует и предупреждает агента через stderr/лог-файл.

set -euo pipefail
INPUT="$(cat)"
FILE_PATH="$(echo "$INPUT" | jq -r '.file_path // ""')"
NEW_CONTENT="$(echo "$INPUT" | jq -r '.new_content // ""')"

LOG_DIR="$(dirname "$0")/../logs"
mkdir -p "$LOG_DIR"

SECRET_PATTERNS=(
  'sk-[a-zA-Z0-9]{20,}'
  'AKIA[0-9A-Z]{16}'
  '-----BEGIN (RSA|EC|OPENSSH) PRIVATE KEY-----'
  'password[[:space:]]*[:=][[:space:]]*[^[:space:]]{4,}'
  'ANTHROPIC_API_KEY[[:space:]]*[:=][[:space:]]*[^[:space:]]{4,}'
)

for pattern in "${SECRET_PATTERNS[@]}"; do
  if echo "$NEW_CONTENT" | grep -Eiq "$pattern"; then
    echo "[$(date -u +%FT%TZ)] SECRET_PATTERN_MATCH file=$FILE_PATH" >> "$LOG_DIR/security-events.log"
    echo "⚠️  Обнаружен потенциальный секрет в $FILE_PATH — проверь перед коммитом." >&2
    break
  fi
done

# afterFileEdit не блокирует — только наблюдательный хук.
exit 0

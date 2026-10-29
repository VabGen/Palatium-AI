#!/usr/bin/env bash
# stop — hash-chained запись в audit log о завершении агентской сессии.

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=lib/audit-chain.sh
source "$SCRIPT_DIR/lib/audit-chain.sh"

INPUT="$(cat)"
if command -v jq >/dev/null 2>&1; then
  CONVERSATION_ID="$(echo "$INPUT" | jq -r '.conversation_id // "unknown"')"
else
  echo "⚠️  session-audit-log: jq не найден — извлекаю conversation_id через python (uv) (audit-chain запись будет пропущена)." >&2
  CONVERSATION_ID="$(printf '%s' "$INPUT" | py_json_field conversation_id 2>/dev/null || echo "unknown")"
fi

audit_append_event "session_stop" "conversation_id" "$CONVERSATION_ID" || true

exit 0

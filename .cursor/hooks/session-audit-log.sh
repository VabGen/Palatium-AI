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
  echo "⚠️  session-audit-log: jq не найден — извлекаю conversation_id через python3 (audit-chain запись будет пропущена)." >&2
  CONVERSATION_ID="$(printf '%s' "$INPUT" | python3 -c "import sys,json; print(json.load(sys.stdin).get('conversation_id') or 'unknown')" 2>/dev/null || echo "unknown")"
fi

audit_append_event "session_stop" "conversation_id" "$CONVERSATION_ID" || true

exit 0

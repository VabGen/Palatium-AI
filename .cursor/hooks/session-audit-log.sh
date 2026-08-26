#!/usr/bin/env bash
# stop — hash-chained запись в audit log о завершении агентской сессии.

set -euo pipefail
INPUT="$(cat)"
CONVERSATION_ID="$(echo "$INPUT" | jq -r '.conversation_id // "unknown"')"

LOG_DIR="$(dirname "$0")/../logs"
LOG_FILE="$LOG_DIR/audit-chain.log"
mkdir -p "$LOG_DIR"
touch "$LOG_FILE"

PREV_HASH="$(tail -n 1 "$LOG_FILE" 2>/dev/null | jq -r '.current_hash // "genesis"' 2>/dev/null || echo "genesis")"
TIMESTAMP="$(date -u +%FT%TZ)"
PAYLOAD="{\"timestamp\":\"$TIMESTAMP\",\"conversation_id\":\"$CONVERSATION_ID\",\"event\":\"session_stop\"}"
CURRENT_HASH="$(printf '%s' "${PREV_HASH}${PAYLOAD}" | sha256sum | awk '{print $1}')"

jq -n \
  --arg ts "$TIMESTAMP" \
  --arg cid "$CONVERSATION_ID" \
  --arg prev "$PREV_HASH" \
  --arg curr "$CURRENT_HASH" \
  '{timestamp:$ts, conversation_id:$cid, event:"session_stop", previous_hash:$prev, current_hash:$curr}' \
  >> "$LOG_FILE"

exit 0

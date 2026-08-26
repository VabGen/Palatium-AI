#!/usr/bin/env bash
# beforeMCPExecution — базовый Zero Trust guard: запрещает вызов MCP-инструментов
# из явного deny-списка (например, продовые деструктивные MCP-tools) без ask-подтверждения.
# stdin JSON: { tool_name, server_name, params, hook_event_name, ... }

set -euo pipefail
INPUT="$(cat)"
TOOL_NAME="$(echo "$INPUT" | jq -r '.tool_name // ""')"

ASK_LIST=(
  "send_email"
  "db_write"
  "financial_transaction"
  "code_execute"
  "delete_"
)

for pattern in "${ASK_LIST[@]}"; do
  if [[ "$TOOL_NAME" == *"$pattern"* ]]; then
    jq -n --arg tool "$TOOL_NAME" '{
      permission: "ask",
      agentMessage: ("Инструмент " + $tool + " требует HITL-подтверждения по политике платформы."),
      userMessage: ("Агент запрашивает выполнение критичного инструмента: " + $tool)
    }'
    exit 0
  fi
done

jq -n '{ permission: "allow" }'

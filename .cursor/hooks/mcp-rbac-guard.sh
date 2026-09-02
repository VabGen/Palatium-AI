#!/usr/bin/env bash
# beforeMCPExecution — Zero Trust guard по закрытому перечню MCP-инструментов (070).
#
# stdin JSON: { tool_name, server_name, params, hook_event_name, ... }

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=lib/audit-chain.sh
source "$SCRIPT_DIR/lib/audit-chain.sh"

if ! require_jq; then
  # failClosed=true для этого хука в hooks.json — без jq мы не можем ни
  # распарсить payload, ни собрать корректный ответ через jq. Печатаем
  # deny вручную (printf, без jq) и НЕ пытаемся писать в audit-chain —
  # audit_append_event сама откажет тем же require_jq.
  printf '{"permission":"deny","agentMessage":"mcp-rbac-guard: jq не найден в PATH, guard не может проверить вызов — fail-closed (020).","userMessage":"Вызов MCP-инструмента заблокирован: guard безопасности недоступен."}'
  exit 0
fi

INPUT="$(cat)"
TOOL_NAME="$(echo "$INPUT" | jq -r '.tool_name // ""')"
SERVER_NAME="$(echo "$INPUT" | jq -r '.server_name // ""')"

# Источник истины — 070-mcp-tools.mdc. Меняешь перечень там — меняешь и здесь,
# в одном PR (055: баг в контракте чинится в контракте, не патчем на узле).
READ_TOOLS=(
  "search_knowledge"
  "search_memory"
  "graph_query"
  "web_fallback"
)

# Мутации/побочные эффекты — требуют HITL (020: interrupt()+Command(resume=...)
# на уровне графа; этот хук — вторая, независимая линия защиты на уровне MCP-вызова).
ASK_TOOLS=(
  "save_memory"
  "forget_memory"
  "consolidate_memory"
  "ingest_document"
)

_in_list() {
  local needle="$1"; shift
  local item
  for item in "$@"; do
    [[ "$needle" == "$item" ]] && return 0
  done
  return 1
}

if _in_list "$TOOL_NAME" "${READ_TOOLS[@]}"; then
  jq -n '{ permission: "allow" }'
  exit 0
fi

if _in_list "$TOOL_NAME" "${ASK_TOOLS[@]}"; then
  audit_append_event "mcp_tool_ask" "tool_name" "$TOOL_NAME" "server_name" "$SERVER_NAME" || true
  jq -n --arg tool "$TOOL_NAME" '{
    permission: "ask",
    agentMessage: ("Инструмент " + $tool + " требует HITL-подтверждения по политике платформы (020)."),
    userMessage: ("Агент запрашивает выполнение критичного инструмента: " + $tool)
  }'
  exit 0
fi

# Не в закрытом перечне 070 — deny by default (Zero Trust), не allow.
# Ловит: опечатку в имени, инструмент, добавленный в MCP-сервер мимо
# ревью, попытку сервера подменить/добавить tool (070: "перечень закрытый").
audit_append_event "mcp_tool_denied_unknown" "tool_name" "$TOOL_NAME" "server_name" "$SERVER_NAME" || true
jq -n --arg tool "$TOOL_NAME" --arg server "$SERVER_NAME" '{
  permission: "deny",
  agentMessage: ("Инструмент " + $tool + " (сервер " + $server + ") отсутствует в закрытом перечне 070-mcp-tools.mdc — deny by default."),
  userMessage: ("Заблокирован вызов неизвестного инструмента: " + $tool)
}'

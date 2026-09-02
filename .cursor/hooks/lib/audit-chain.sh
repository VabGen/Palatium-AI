#!/usr/bin/env bash
# lib/audit-chain.sh — общая функция hash-chained записи в audit-chain.log.
# Источник истины для формулы хэша и обработки повреждённой цепочки —
# единственное место, где это реализовано (050: не дублировать по файлам).
#
# Формула: current_hash = sha256(previous_hash + sha256(canonical_json(payload)))
# canonical_json — jq -cS (сортированные ключи, без пробелов).
#
# Использование из другого хука:
#   source "$(dirname "$0")/lib/audit-chain.sh"
#   audit_append_event "tool_denied" '{"tool_name":"'"$TOOL_NAME"'"}'

_AUDIT_LOG_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/../../logs" && pwd)"
_AUDIT_LOG_FILE="${_AUDIT_LOG_DIR}/audit-chain.log"
_AUDIT_LOCK_FILE="${_AUDIT_LOG_DIR}/.audit-chain.lock"

# require_jq — вызывай ПЕРВОЙ строкой в любом хуке, использующем jq.
# Без jq audit_append_event (и весь парсинг JSON в этих хуках) не работает —
# это должно быть громко, а не "jq: command not found" посреди скрипта.
# Возвращает 1, если jq недоступен; сообщение — в stderr, решение
# fail-open/fail-closed остаётся за вызывающим хуком (у них разная семантика).
require_jq() {
  if ! command -v jq >/dev/null 2>&1; then
    echo "🚨 $(basename "${BASH_SOURCE[1]:-$0}"): jq не найден в PATH — хук не может выполниться корректно." >&2
    return 1
  fi
  return 0
}

# audit_append_event <event_type> <extra_json_object>
# extra_json_object — валидный JSON-объект (может быть "{}"), сливается в запись.
# audit_append_event <event_type> [key1 value1 [key2 value2 ...]]
# ВАЖНО: extra-поля передаются как плоские key/value пары, а НЕ как готовый
# jq-JSON от вызывающего кода. Первая версия принимала "$(jq -n ...)" вторым
# аргументом — это вызывало jq на call site, ДО входа в функцию и ДО
# require_jq-проверки внутри неё; под set -euo pipefail отсутствие jq валило
# весь хук прямо там, а не давало дойти до аккуратного warning. Теперь jq
# вызывается только один раз, внутри уже проверенной функции.
audit_append_event() {
  local event_type="$1"; shift || true

  require_jq || { echo "⚠️  audit-chain: событие $event_type НЕ записано (jq недоступен)" >&2; return 1; }

  mkdir -p "$_AUDIT_LOG_DIR"
  touch "$_AUDIT_LOG_FILE"

  # Эксклюзивная блокировка на весь read-modify-write: без неё две параллельные
  # сессии, пишущие одновременно, могут прочитать один и тот же previous_hash
  # и создать вилку в цепочке вместо линейной последовательности.
  exec 9>"$_AUDIT_LOCK_FILE"
  flock -w 5 9 || {
    echo "⚠️  audit-chain: не удалось получить lock за 5с, событие $event_type НЕ записано" >&2
    return 1
  }

  local prev_hash
  local last_line
  last_line="$(tail -n 1 "$_AUDIT_LOG_FILE" 2>/dev/null || true)"

  if [[ -z "$last_line" ]]; then
    # Файл пуст — это настоящий genesis, а не повреждение.
    prev_hash="genesis"
  else
    prev_hash="$(printf '%s' "$last_line" | jq -r '.current_hash // empty' 2>/dev/null || true)"
    if [[ -z "$prev_hash" ]]; then
      # Последняя строка есть, но не парсится / без current_hash — это
      # ПОВРЕЖДЕНИЕ цепочки, не genesis. Тихий откат в genesis скрыл бы
      # подделку/обрыв записи. Кодируем факт повреждения прямо в prev_hash,
      # чтобы это навсегда осталось видно в самой цепочке, и громко пишем в stderr.
      local corrupt_marker
      corrupt_marker="CHAIN-CORRUPTED-$(printf '%s' "$last_line" | sha256sum | awk '{print $1}')"
      prev_hash="$corrupt_marker"
      echo "🚨 audit-chain: последняя запись в $_AUDIT_LOG_FILE не парсится — цепочка помечена как CORRUPTED, не сброшена в genesis" >&2
    fi
  fi

  local timestamp
  timestamp="$(date -u +%FT%TZ)"

  # Собираем --arg на каждую пару key/value и динамический jq-фильтр —
  # единственное место во всей библиотеке, где реально вызывается jq
  # для построения payload.
  local jq_args=(--arg ts "$timestamp" --arg event "$event_type")
  local jq_filter='{timestamp: $ts, event: $event}'
  local idx=0
  while [[ $# -ge 2 ]]; do
    idx=$((idx + 1))
    jq_args+=(--arg "k${idx}" "$1" --arg "v${idx}" "$2")
    jq_filter="${jq_filter} + {(\$k${idx}): \$v${idx}}"
    shift 2
  done

  local canonical_payload
  canonical_payload="$(jq -cS -n "${jq_args[@]}" "$jq_filter")"

  local inner_hash current_hash
  inner_hash="$(printf '%s' "$canonical_payload" | sha256sum | awk '{print $1}')"
  current_hash="$(printf '%s' "${prev_hash}${inner_hash}" | sha256sum | awk '{print $1}')"

  jq -cS -n \
    --argjson payload "$canonical_payload" \
    --arg prev "$prev_hash" \
    --arg curr "$current_hash" \
    '$payload + {previous_hash: $prev, current_hash: $curr}' \
    >> "$_AUDIT_LOG_FILE"

  flock -u 9
  exec 9>&-
}

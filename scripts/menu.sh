#!/usr/bin/env bash
# scripts/menu.sh — интерактивное меню Palatium-AI (bash, стрелки ↑↓)
set -euo pipefail

ENV_FILE="${ENV_FILE:-env/.env}"

items=(
  "🚀  Первый запуск (reset + build + up)"
  "▶️   Поднять стек (up -d --build)"
  "🔄  Перезапустить без пересборки"
  "⏹️   Остановить стек (down)"
  "💥  Полный reset (down -v)"
  "📋  Статус сервисов (ps)"
  "📜  Логи всех сервисов"
  "📜  Логи litellm"
  "📜  Логи api"
  "✅  Проверить endpoint"
  "🗄️   Миграции Alembic"
  "🐘  Список БД Postgres"
  "🔌  LiteLLM models"
  "🤖  Тестовый tier-mid"
  "🐚  Shell в api"
  "🛠️   Валидация compose"
  "🌐  Swagger UI"
  "🌐  LiteLLM UI"
  "❌  Выход"
)

compose() { docker compose --env-file "$ENV_FILE" "$@"; }

run_action() {
  case "$1" in
    0) compose down -v; compose up -d postgres; sleep 5; compose up -d --build ;;
    1) compose up -d --build ;;
    2) compose up -d ;;
    3) compose down ;;
    4) read -p "Удалить volumes? (y/N) " c; [[ "$c" == "y" ]] && compose down -v ;;
    5) compose ps ;;
    6) compose logs -f ;;
    7) compose logs -f litellm ;;
    8) compose logs -f api ;;
    9) curl -sf http://localhost:8000/health && echo " API ✅"; \
       curl -sf http://localhost:4000/health/liveliness && echo " LiteLLM ✅" ;;
    10) compose exec api alembic upgrade head ;;
    11) compose exec postgres psql -U postgres -c "\l" ;;
    12) curl -sf -H "Authorization: Bearer sk-palatium-master" \
          http://localhost:4000/v1/models | python -m json.tool ;;
    13) curl -sf http://localhost:4000/v1/chat/completions \
          -H "Authorization: Bearer sk-palatium-master" \
          -H "Content-Type: application/json" \
          -d '{"model":"tier-mid","messages":[{"role":"user","content":"Say OK"}]}' \
          | python -m json.tool ;;
    14) compose exec api sh ;;
    15) compose config --quiet && echo "✅ OK" ;;
    16) python -c "import webbrowser; webbrowser.open('http://localhost:8000/docs')" ;;
    17) python -c "import webbrowser; webbrowser.open('http://localhost:4000/ui')" ;;
    18) exit 0 ;;
  esac
}

selected=0
total=${#items[@]}

while true; do
  clear
  echo "╔══════════════════════════════════════════════════════════╗"
  echo "║       🏛️  PALATIUM-AI — Панель управления                ║"
  echo "╚══════════════════════════════════════════════════════════╝"
  echo
  for i in "${!items[@]}"; do
    if [[ $i -eq $selected ]]; then
      printf " ► \033[1;44m%s\033[0m\n" "${items[$i]}"
    else
      printf "   %s\n" "${items[$i]}"
    fi
  done
  echo
  echo " ↑↓ — навигация · Enter — выбрать · q — выход"

  IFS= read -rsn1 key
  case "$key" in
    $'\x1b')
      read -rsn2 rest
      case "$rest" in
        '[A') selected=$(( (selected - 1 + total) % total )) ;;
        '[B') selected=$(( (selected + 1) % total )) ;;
      esac
      ;;
    '')
      run_action "$selected"
      echo; echo "Нажмите Enter для возврата..."; read -r
      ;;
    q|Q) exit 0 ;;
  esac
done

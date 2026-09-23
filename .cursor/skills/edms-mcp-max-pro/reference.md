# EDMS MCP — reference (коротко)

Читать через skill при спорных решениях; не дублировать 090/070 целиком.

**Полный MCP-план Host/stubs/gateway:** `.cursor/plans/mcp-roadmap.md` (canvas `mcp-full-plan`).

## Track A — уже сделано (не переизобретать)

| Phase | Что |
|-------|-----|
| 1 | FastMCP Streamable HTTP stubs + Host Client |
| 2 | Platform local execution only (stub refuse fake write) |
| 3 | JWT `aud=mcp:<server>` + MultiAuth |
| 4 | Schema SoT: `domain/mcp/*_schemas.py` |
| 5 | Host pin gate / argument_policy / strip annotations |
| 6 | Gateway ProxyProvider + pin allowlist scaffold |

## Track B — DONE (Host, не EDMS)

Platform static pin discovery; нет зависимости от `:8082`.
Волны B1–B6 — в `mcp-roadmap.md`. Не смешивать с EDMS W0–W7.

## Track C — этот скилл

Legacy AI-Assistant → laconic EDMS adapter; JavaEdms read-only; волны W0–W7 в `waves.md`.
W0 inventory: 2026-09-04 (см. отчёт в чате / roadmap).

## Где править

| Нужно | Куда |
|-------|------|
| EDMS stub/adapter | `mcp_servers/edms/` (не JavaEdms) |
| Pin + schema | `external_schemas.py`, `tool_policy.py` |
| Gateway | `mcp_servers/gateway/` |
| Host HITL/ACL | Researcher + `call_mcp_tool` |
| Platform local discovery | `registry.py` + `bootstrap.py` (Track B) |
| Справка СЭД | `mcp_servers/edms/JavaEdms/**` READ ONLY |

## Анти-паттерны из junior/чат-кода

- Один HTTP-клиент на все экраны СЭД без контракта
- Строковые статусы/типы документов без Literal из JavaEdms
- «Успешный» archive/upload без проверки ответа API
- Промпт вместо RBAC/HITL
- Подмешивание UI-роутов фронта в tool args

## Когда звать пользователя

- Нет endpoint/auth в JavaEdms после поиска
- Конфликт двух JavaEdms модулей (какой API канон)
- Новый tool вне текущего pin-набора
- Нужны креды/стенд — только env, не в чат
- **Legacy AI-Assistant файлы** ещё не в репо — без них W1 intent map неполный

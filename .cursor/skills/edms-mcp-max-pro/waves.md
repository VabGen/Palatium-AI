# EDMS MCP — волны MAX PRO

При противоречии с правилами (090/092/070/020) — **правила побеждают**; обнови
этот файл, если разошлись.

Default: одна волна за ход. Scope «весь EDMS» → начни **W0**, жди «дальше».

| Wave | Scope | Цель |
|------|--------|------|
| **W0** | Карта | Inventory: JavaEdms + edms-ai-assistant + старый `edms_mcp_server.py` (все — reference) + pins/gateway; **предложить layout новой структуры** под `mcp_servers/edms/`; без прод-кода |
| **W1** | Контракты | Закрытый набор EDMS tools (имена, I/O pydantic, R/W, HITL); сверить с JavaEdms; gaps → вопросы |
| **W2** | Read path | Реализовать/укрепить read tools (search/get/list) против реального или stub upstream; empty/deny сценарии |
| **W3** | Write path | Write tools + Host HITL + idempotency; never fake success |
| **W4** | Auth & tenancy | Схема auth СЭД (из JavaEdms/user) → env secrets; actor/tenant bind; aud=mcp:edms |
| **W5** | Adapter cutover | Stub → real adapter за тем же pin schema; gateway `MCP_UPSTREAM_URL` optional |
| **W6** | Scenarios & evals | Матрица пользовательских запросов + unit/adversarial drills; grader на класс багов |
| **W7** | Harden | Mask errors, timeouts, circuit, PII redaction, progressive disclosure; production-audit slice |

## Что не входит в волны

- Рефакторинг JavaEdms / перенос Java в Python
- God-tool «сделай всё в СЭД»
- UI чата AI-Assistant (кроме извлечения intent)
- Platform MCP tools (отдельный Host local handler)

## Handoff пользователю

После каждой волны явно:

1. Какие **файлы legacy** ещё нужны (если gaps).
2. Какие **вопросы по API/auth** без ответа в JavaEdms.
3. Можно ли `дальше` на W+1 или `FIX` текущей.

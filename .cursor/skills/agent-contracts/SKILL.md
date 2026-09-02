---
name: agent-contracts
description: >-
  Use when the user asks to create, scaffold, or extend an agent, tool contract,
  or MCP tool schema for the platform (new agents from scratch).
  НЕ применять: миграция legacy *_agent.py на BaseAgent (agent-refactoring),
  ревью существующего кода (code-revision / max-pro-review).
---

# Agent & Contract Scaffolding

Используй при создании нового агента, инструмента или межагентного контракта.
При противоречии этого скилла и правил — правила (индекс: 099).

## Шаг 1 — сверка с реестром
Спроси/сверь: какая роль из **реестра агентов (000 — единый источник)** закрывается?
Если задача не укладывается ни в одну роль — предложи ближайшую существующую роль
вместо создания нового агента без согласования с пользователем.

## Шаг 2 — генерация контракта

Всегда генерируй в этом порядке:
1. `AgentConfig` — состав полей и типы **только по 030**; значения
   timeout/retry/threshold — из settings/config.py (050, без литералов в коде).
2. Input-схема (Pydantic, frozen где применимо); Literal-наборы — в `core/types` /
   `domain/policies` (055), не инлайн.
3. Output-схема (`TaskResult`-совместимая).
4. `allowed_tools` — минимально достаточный набор; >5 — с обоснованием в config.py (050).
5. Реализация методов контракта 030: `run`, `get_required_context_keys`,
   `get_available_tools`, `verify`. LLM/MCP-вызовы — **только через
   `execute_with_guardrails`** (единая точка, порт `domain/ports/harness.py`, 065);
   данные — JIT-ключами (input_keys).
6. Confidence-gate — через CriticPolicy (055), не рукописный в методе;
   низкий confidence → `status="partial"` + HITL-эскалация (020).
7. Трассировка на узле; метрики — из реестра `palatium_*` (040) на значимые события.

## Шаг 3 — MCP-инструмент (если нужен новый tool)

- Перечень инструментов — **закрытый, по 070**; новый tool — только если он
  в перечне или явно согласован. Схема — `ToolDefinition` (070).
- `inputSchema` — JSON Schema draft 2020-12, валидируется на клиенте до сетевого вызова.
- Ответ `tools/call` парсится в Pydantic-модель, не читается как сырой `dict`.
- RBAC-фильтрация — в harness/execute_with_guardrails, до вызова (070); не дублировать в узле.
- Ошибки JSON-RPC — в audit с `thread_id` и `tool_id` (040).
- Tool descriptions — first-class prompt engineering (ACI = HCI): как документация
  для junior-разработчика, с examples в schema.

## Шаг 4 — HITL-проверка

Если у инструмента побочный эффект (email/db-write/финансы/PII/code-exec) —
**`interrupt()` + `Command(resume=...)`** (020) и сгенерируй `HITLCard`
(карточка, не текстовый список вариантов). `interrupt_before` — устаревший API, запрещён.

## Выходной формат

Файлы в порядке: schemas → agent implementation → tool/MCP contract (если есть) →
краткий summary из 3–5 строк, что добавлено и как встраивается
(узел в `orchestration/nodes.py`, регистрация в реестре 000).

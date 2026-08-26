---
name: agent-contracts
description: Use when the user asks to create, scaffold, or extend an agent, tool contract, or MCP tool schema for the platform.
---

# Agent & Contract Scaffolding

Используй этот skill при создании нового агента, инструмента или межагентного контракта.

## Шаг 1 — сверка с реестром
Спроси/сверь: какая из 12 ролей реестра (`000-architecture.mdc`) закрывается? Если задача не
укладывается ни в одну роль — предложи, к какой существующей роли она ближе всего, вместо
создания 13-го агента без согласования с пользователем.

## Шаг 2 — генерация контракта

Всегда генерируй в этом порядке:
1. `AgentConfig` — см. `030-agent-contracts.mdc` за полным шаблоном.
2. Input-схема (Pydantic, frozen где применимо).
3. Output-схема (`TaskResult`-совместимая).
4. `allowed_tools` — минимально достаточный набор (≤5), с явным обоснованием каждого.
5. Реализация `execute()` с retry/timeout/confidence-gate.
6. Точка трассировки + минимум одна метрика.

## Шаг 3 — MCP-инструмент (если агенту нужен новый tool)

- 1 внешняя система = 1 MCP-сервер (не смешивай Postgres и Slack в одном сервере).
- `inputSchema` — JSON Schema draft 2020-12, валидируется на клиенте до сетевого вызова.
- Ответ `tools/call` парсится в Pydantic-модель, не читается как сырой `dict`.
- Ошибки JSON-RPC логируются в audit с `thread_id` и `tool_id`.

## Шаг 4 — HITL-проверка

Если у инструмента есть побочный эффект (email/db-write/финансы/PII/code-exec) — оберни вызов
в `interrupt_before` и сгенерируй `HITLCard` (карточка, не текстовый список вариантов).

## Выходной формат

Выдавай файлы в порядке: schemas → agent implementation → tool/MCP contract (если есть) →
краткий summary из 3-5 строк, что добавлено и куда это встраивается в StateGraph.

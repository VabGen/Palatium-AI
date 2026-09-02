---
name: code-revision
description: >-
  Use when the user asks to review, revise, or audit agent/platform code for
  architecture, typing, security or HITL compliance before merge.
  НЕ применять: волны MAX PRO по пакетам (max-pro-review), red-team/attack
  surfaces (adversarial-review), аудит живой системы (production-audit).
---

# Code Revision — ZeroTrust Agent Platform

Проверяй код по чек-листу, в этом порядке. Для каждого пункта — явный вердикт
`OK` / `WARN` / `BLOCK` с файлом:строкой.
При противоречии чек-листа и правил — правила (индекс: 099).

## 1. Архитектура (BLOCK при нарушении)
- Слои: domain не импортирует infrastructure/presentation/SDK; application не
  импортирует presentation (000). Зависимости только вниз; core доступен всем.
- Агент реализует ровно одну роль из **реестра агентов (000 — единый источник)**,
  не смешивает ответственности.
- Supervisor/Planner не содержат исполняющих инструментов (030).
- Ось/политика в коде узла вместо `domain/policies/`? → BLOCK (055).
- Hardcode фраз/регексов приветствий/маршрутов? → BLOCK, чинить политикой (055).

## 2. Типизация (BLOCK при нарушении)
- Нет `Any`, непараметризованных `dict`/`list` на границах (010).
- Все I/O — Pydantic-модели с `Field(...)`-ограничениями.
- Literal-наборы — в `core/types` / `domain/policies`, не инлайн в узлах (055).
- Пройдёт ли `mypy --strict`? Если сомнительно — укажи, где упадёт.

## 3. Безопасность / HITL (BLOCK при нарушении)
- Действие из критического списка (email, db-write, финансы, PII, code-exec)?
  → HITL: **`interrupt()` + `Command(resume=...)`** + HITL-карточка (020).
  `interrupt_before` — устаревший API, BLOCK.
- RBAC/allow-list проверяется **в harness** (`execute_with_guardrails`, 065),
  не дублируется в узле; до вызова инструмента (070).
- Нет секретов в коде/логах/промптах (перечень паттернов — 020, не дублировать).

## 4. Отказоустойчивость (WARN при отсутствии)
- Timeout и retry/backoff заданы **через конфиг** (значения — не в коде; 050).
- Confidence threshold проверяется перед возвратом успеха (стратегия — CriticPolicy, 055).
- Есть fallback-модель / fallback-путь при сбое инструмента (LLM: fallback ≥2).

## 5. Observability (WARN при отсутствии)
- Узел обёрнут трассировкой (040).
- Метрики — из реестра `palatium_*` (040) на значимые события; «метрика ради
  галочки на каждый узел» — WARN как шум.
- Критичное действие пишет audit-событие (040/020).

## 6. Тесты / grader (WARN при отсутствии)
- Behavior claimed ⇒ тест или grader (075): deterministic на PR, llm_judge на nightly.

## Формат вывода ревью

```
### Вердикт: [ready to merge | needs changes | blocked]

BLOCK:
- <файл>:<строка> — <проблема> → <как исправить> (правило)

WARN:
- <файл>:<строка> — <проблема> → <рекомендация>

OK:
- <что уже сделано правильно, кратко>
```

Не переписывай весь файл молча — сначала вердикт; изменения только по запросу
пользователя или для BLOCK-пунктов, которые нельзя смержить как есть.
FIX-режим: только BLOCK-и этой ревизии, без scope creep.

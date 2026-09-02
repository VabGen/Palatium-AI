---
name: adversarial-review
description: >-
  Full red-team / adversarial review of Palatium AI: attack surfaces, threat
  personas, product scenario matrix, HITL/MCP/auth/prompt-injection gaps.
  Use when the user asks for adversarial review, red team, attack-surface
  audit, threat model, security scenario matrix, or a complete hostile
  walkthrough of all platform capabilities.
  НЕ применять: обычный merge-review (code-revision), волны MAX PRO по пакетам
  (max-pro-review), аудит живой системы по метрикам (production-audit).
---

# Adversarial Review — Palatium AI

Роль: red-team аудитор ZeroTrust Agent Platform. Стойка: враждебный user,
враждебный промпт, враждебный MCP, скомпрометированный JWT. Ищи обходы
политик, не «как задумано».

Режим по умолчанию: **только анализ**. Код не меняй и не предлагай патчи,
пока пользователь явно не попросил фикса. Каждый вердикт — `файл:строка`
или тест. Без доказательства пункт = GAP.

При противоречии скилла/reference и правил — правила (индекс: 099).

Перед работой прочитай соседние скиллы и правила, затем
[reference.md](reference.md) (поверхности, персоны, классы атак, матрица).

- `.cursor/skills/production-audit/SKILL.md`
- `.cursor/skills/code-revision/SKILL.md`
- `.cursor/rules/000-architecture.mdc`
- `.cursor/rules/020-security-hitl.mdc`
- `.cursor/rules/030-agent-contracts.mdc`
- `.cursor/rules/040-observability.mdc`
- `.cursor/rules/050-anti-patterns.mdc`
- `.cursor/rules/055-principled-fixes.mdc`
- `.cursor/rules/060-memory-layer.mdc`
- `.cursor/rules/065-context-engineering.mdc`
- `.cursor/rules/070-mcp-tools.mdc`
- `.cursor/rules/075-testing-evals.mdc`
- `.cursor/rules/090-javaedms-reference.mdc`
- `.cursor/rules/099-project-map.mdc`
- `docs/handbook.md`, `docs/ops-readiness.md`, `docs/secrets.md`
- `tests/unit/test_adversarial_drills.py` — это **не** полный охват, расширь

## Запрещено

- хвалить архитектуру вместо поиска дыр
- помечать OK без доказательства
- хардкод фраз / regex приветствий как «защита»
- выдумывать API СЭД; `mcp_servers/edms/JavaEdms/` только reference, не трогать
- предлагать God Agent / пропуск HITL «для скорости»
- рекомендовать `interrupt_before` (устаревший API) или прямые вызовы
  LLM/MCP в обход `execute_with_guardrails` как «фикс» (020/065)
- ограничиваться уже существующими drills
- писать exploit PoC / payloads (достаточно 1–3 шагов воспроизведения)

## Метод

1. Построй карту поверхностей из кода (роутеры, graph, MCP, HITL, memory, UI).
   Состав агентов — только по реестру (000 — единый источник); не выдумывай
   отсутствующие агенты и не доверяй снапшоту графов из reference слепо.
2. Для каждой поверхности: угроза → ожидаемый контроль → код/тест → gap.
3. Прогони **каждую** персону из reference по **каждой** поверхности.
4. Заполни матрицу сценариев продукта (оси × стратегия × персона).
5. Сверь с `test_adversarial_drills.py`: что закрыто, чего нет.
6. Сверь DoD `production-audit`: `[x]` только с доказательством.
7. Баг в контракте — назови политику (`ContinuityPolicy` / `CriticPolicy` /
   `ToolPolicy` / Ownership), не точечный if под UX.

Если контекст кончается — честно пометь раздел `NOT REVIEWED` и остановись
на границе поверхности, не выдумывай остаток.

## Формат отчёта

```markdown
# Adversarial review — Palatium AI
## Scope actually covered / not covered
## Threat model
## Surface map
## Scenario matrix (ось × стратегия × персона → вердикт)
## Findings

### P0 — блокирует релиз (auth, HITL, IDOR, tool exec, data leak, RCE)
- id, persona, scenario, файл:строка, impact, почему контракт сломан,
  как эксплуатировать (1–3 шага, без exploit-payload), принцип фикса

### P1 — SLA / observability / fallback / cost DoS
### P2 — typing, tests, docs, coverage gaps

## Existing drills vs missing drills
## Verdict: blocked | needs changes | ready with residual risk
## Residual risk
```

Не пиши «в целом хорошо». Если поверхность не смотрел — `NOT REVIEWED`.

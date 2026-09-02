---
name: production-audit
description: >-
  Use when the user asks for a production readiness audit, DoD check,
  security drill review, or pre-release gate for the platform.
  НЕ применять: точечный PR-ревью (code-revision), волны MAX PRO по пакетам
  (max-pro-review), red-team/attack surfaces (adversarial-review) — этот
  скилл проверяет **release gate по метрикам DoD**, не ищет новые дыры.
---

# Production Audit — Definition of Done

Прогони репозиторий/PR по этому чек-листу. Для каждого пункта — `[x]` выполнено
с указанием файла-доказательства (или теста/дашборда), `[ ]` не выполнено с
конкретным gap. Общие формулировки вида «вроде реализовано» не считаются
доказательством.

При противоречии чек-листа и правил — правила (индекс: 099).
Источники находок для этого чек-листа — предыдущие волны `max-pro-review` и
отчёты `adversarial-review`; этот скилл не проводит собственный код-ревью
заново, а сверяет их результат с DoD.

## Архитектура и типы

```
[ ] Каждый агент — единственная ответственность из реестра (000) + Pydantic I/O (030)
[ ] mypy --strict проходит без ошибок и необоснованных `# type: ignore` (010)
[ ] Supervisor/Planner не содержат execution-инструментов в allowed_tools (030)
[ ] Literal-оси (task_kind/continuation_kind/strategy) объявлены один раз в
    domain/policies/types.py, не задублированы по агентам (055)
```

## Оркестрация и отказоустойчивость

```
[ ] StateGraph покрывает retry / timeout / fallback / human-escalation на условных рёбрах (065)
[ ] execute_with_guardrails — единственная точка запуска агента из узла (065);
    нет прямых вызовов LLM/MCP в обход неё
[ ] Circuit Breaker: closed → open → half-open → closed протестирован drill'ом,
    порог сбоев и cooldown — из конфига, не хардкод (020)
[ ] Kill Switch протестирован: новые запуски графа отклоняются, in-flight
    завершают текущий узел; переключение пишется в audit (020)
[ ] LLM fallback-цепочка ≥2 независимых провайдера (020)
[ ] MAX_REVISIONS на цикле Critic → доработка — константа конфига, не бесконечный цикл (065)
```

## RBAC / HITL

```
[ ] RBAC allow-list проверяется в ToolRegistry/harness на каждый tool call,
    не дублируется в узлах (020, 070)
[ ] HITL реализован: email / db-write / EDMS-write / графовые мутации /
    финансы / PII / code-exec / confidence < порога (020)
[ ] HITL-выбор — кликабельные карточки с card_id, TTL по классу действия
    (обратимое 30 мин / необратимое 5 мин), не текстовый список (020)
[ ] Карточка одноразовая: повторный ответ на тот же card_id отклоняется,
    проверка состояния — по Redis, не по UI (020)
[ ] risk_score вычисляется из класса действия + confidence, не хардкодится;
    эскалация к менеджеру при risk_score выше порога (020)
[ ] interrupt() + Command(resume=...) используется везде; interrupt_before
    (устаревший API) отсутствует в кодовой базе (020)
```

## Данные и память

```
[ ] Row-Level Security по user_id на memory.entries, app-роль БД без BYPASSRLS (060)
[ ] Секреты не встречаются в коде/логах/git-истории/промптах;
    secret scanner подключён перед логированием и записью в память (020, 040, 060)
[ ] PII в long-term память — только с contains_pii=true и правилом забывания,
    молчаливой записи PII нет (060)
[ ] Мутации памяти (save/forget/consolidate) идут только через MCP-инструменты
    поверх MemoryPort, не прямым SQL из агента (060, 070)
[ ] Параметризованные SQL/Cypher везде; конкатенация строк запроса отсутствует (070)
```

## Observability

```
[ ] 100% узлов StateGraph обёрнуты span'ом (OTel — primary; LangSmith,
    если включён, — вторичный экспортёр, не отдельные @traceable-декораторы) (040)
[ ] Метрики palatium_* из единого реестра (040) на значимые события,
    без метрик-ради-галочки на каждый узел
[ ] Hash-chained audit log: append-only на уровне БД (нет UPDATE/DELETE у app-роли),
    периодическая верификация цепочки от genesis настроена (не реже раза в сутки) (040)
[ ] LLM-as-a-Judge — quality gate перед финализацией критичных выходов;
    судья — модель другого провайдера, чем генератор; low-risk стратегии
    (ack_only/format_only/small_talk) проходят без судьи по CriticPolicy (040, 055)
```

## Тесты и evals

```
[ ] Бенчмарк (100+ задач) success rate > 85%, отчёт в артефактах CI (075)
[ ] evals/baseline.json в репозитории; nightly-сравнение score ≥ baseline − tolerance,
    авто-revert baseline запрещён (075)
[ ] Load test: 1000+ параллельных сессий, p95 latency в SLA
[ ] Coverage domain/policies ≥ 90% (075)
[ ] Ни один тест/eval не ослаблен, чтобы «прошёл»; спорные ожидания — через
    обсуждение, не тихую правку (050, 075)
```

## Антипаттерны (жёсткий стоп-лист)

```
[ ] Нет God Agent / God Object (000, 050)
[ ] Нет агента с >5 инструментами без обоснования в config.py (050, 070)
[ ] Нет dict[str, Any] как межагентного контракта (010, 050)
[ ] mcp_servers/edms/JavaEdms/** не изменён (090)
```

## Приоритизация находок

Отчёт всегда завершай тремя блоками (та же шкала, что в `adversarial-review`
и `max-pro-review`, чтобы находки были сопоставимы между скиллами):

```
### P0 — блокирует релиз (security, HITL, data loss risk)
### P1 — блокирует production SLA (observability, fallback, load)
### P2 — технический долг (типизация, тесты, документация)
```

Не помечай пункт как выполненный без конкретной ссылки на файл/строку/тест,
который это доказывает — общих утверждений вида «вроде реализовано» недостаточно.
Если пункт не проверялся в этом прогоне — помечай `NOT REVIEWED`, а не `[ ]`
(чтобы не путать «не сделано» и «не смотрели»).

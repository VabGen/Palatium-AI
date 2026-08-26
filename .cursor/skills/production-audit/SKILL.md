---
name: production-audit
description: Use when the user asks for a production readiness audit, DoD check, security drill review, or pre-release gate for the platform.
---

# Production Audit — Definition of Done

Прогони репозиторий/PR по этому чек-листу. Для каждого пункта — `[x]` выполнено с указанием
файла-доказательства, `[ ]` не выполнено с конкретным gap.

```
[ ] Каждый агент — единственная ответственность + Pydantic I/O-схемы
[ ] mypy --strict проходит без ошибок и необоснованных ignore
[ ] StateGraph покрывает retry / timeout / fallback / human-escalation
[ ] RBAC allow-list проверяется на каждый tool call
[ ] HITL реализован: email / db-write / финансы / PII / code-exec
[ ] HITL-выбор пользователю — кликабельные карточки, не текстовый список
[ ] Circuit Breaker (3 сбоя подряд) и Kill Switch протестированы drill'ом
[ ] Hash-chained audit log пишется на каждое критичное действие
[ ] 100% LangSmith tracing + Prometheus метрики на каждый узел
[ ] LLM-as-a-Judge quality gate перед финализацией критичных выходов
[ ] Бенчмарк (100+ задач) success rate > 85%
[ ] Load test: 1000+ параллельных сессий, p95 latency в SLA
[ ] Fallback-цепочка LiteLLM ≥2 независимых провайдера
[ ] Секреты не встречаются в коде/логах/git-истории
[ ] Нет God Agent / God Object / >5 инструментов на агента
```

## Приоритизация находок

Отчёт всегда завершай тремя блоками:

```
### P0 — блокирует релиз (security, HITL, data loss risk)
### P1 — блокирует production SLA (observability, fallback, load)
### P2 — технический долг (типизация, тесты, документация)
```

Не помечай пункт как выполненный без конкретной ссылки на файл/строку/тест, который это
доказывает — общих утверждений вида "вроде реализовано" недостаточно.

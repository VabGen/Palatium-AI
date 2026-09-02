# Adversarial review — каталог поверхностей и сценариев

Читай целиком при скилле `adversarial-review`. Не выдумывай поверхности, которых
нет в репозитории; сначала сверь grep/read.
⚠️ Этот файл — снапшот поверхностей. Перечни осей/стратегий/агентов — копии
контрактов: источники — 055 (оси/стратегии), 000 (реестр агентов), 070 (tools).
При расхождении снапшота и правил — правила и обнови снапшот.

## 1. Карта поверхностей

### API (`presentation`) — без изменений (таблица как была)

### Граф оркестрации

Intent (ось `task_kind`) → ContinuityPolicy → Supervisor → context_enricher
→ Worker(s) по реестру 000 → Critic → Formatter → MemoryKeeper / consolidation.
⚠️ ContextWeaver/Contextualizer как отдельные узлы устарели (055: слиты в
context_enricher). Сверяй фактический граф с `orchestration/` и реестром 000.

### Оси продукта (комбинируй, не проверяй по одной)

Перечни `task_kind` / `continuation_kind` / `strategy` — как в снапшоте;
**источник истины — 055 / `core/types`** (`task_kind`, `continuation_kind`,
`RouteStrategy` — закрытые Literal-реестры).

Флаги среды хода: HITL on/off, kill switch, circuit open, budget exceeded,
MCP down, low confidence, fallback LLM, empty/malformed memory.

### MCP / tools — как было + «перечень и ToolDefinition — 070»

### Контекст / харнесс — «execute_with_guardrails — единая точка, 065»

`Harness.execute_with_guardrails` — единственный путь вызова агента из узла
графа (span → JIT-контекст → RBAC-фильтр → secret scan → run → verify →
confidence gate → метрики). Любой узел, вызывающий LLM/tool/агента в обход
этой точки — сама по себе находка (обход трассировки, RBAC, guardrails).

## 2. Модель злоумышленника — без изменений (A–H)

## 3. Классы атак

### MCP / tools
- `tools/call` с чужим name, `additionalProperties`, path traversal в args
- side_effect write **без `interrupt()` + `Command(resume=...)` + HITL-карточки** (020)
- подмена `riskTier` / `readOnlyHint` сервером
- SSRF / command inject в `argument_policy`
- tool output в промпт без санитизации (indirect injection)
- RBAC-проверка не в harness (`execute_with_guardrails`, 065), а в узле — дубль/обход

### Prompt / agent
- … (как было, кроме:)
- tool count: **>5 без обоснования в config.py** (050) / tool не в `allowed_tools`
- `confidence < threshold` проходит как success — **порог должен идти из
  CriticPolicy** (055); свободная переменная/константа = GAP
- circuit не открывается — **порог из config**, а не «после 3 fail»

### HITL
- … (как было, кроме:)
- `risk_score` выше порога эскалации (порог — из config/политики) не эскалирует менеджеру
- replay ответа на уже обработанный/просроченный `card_id` не отклоняется
  (проверка состояния карточки должна идти по Redis, не по UI-состоянию, 020)

### Data / memory, Reliability/cost, Observability, UI — как было
(`TURN`/`DAILY` budget, audit hash-chain, XSS ChatShell и т.д.)

## 4. Матрица сценариев — как было, с правками:
- №9: write-like tool → **`interrupt()` + Command(resume=...)** + карточка
- №13: низкий confidence Critic (порог из CriticPolicy)

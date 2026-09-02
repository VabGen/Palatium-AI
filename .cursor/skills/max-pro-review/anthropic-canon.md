# Anthropic Engineering Canon → Palatium AI

Источник: [Engineering at Anthropic](https://www.anthropic.com/engineering).
Это **эталон проектирования** агентных систем. При MAX PRO review сверяй
находки с этими принципами; «красивый код» без соответствия — WARN.

Ниже — сжатые инварианты + маппинг на слои Palatium. Полные тексты — по URL.
Порядок волн ревью — отдельно, в [waves.md](waves.md). При противоречии этого
файла и правил проекта (индекс: 099) — правила.

---

## A. Архитектура агентов

### Building effective agents (Dec 2024)
https://www.anthropic.com/engineering/building-effective-agents

| Принцип | Смысл | Palatium |
|---------|--------|----------|
| Workflows vs Agents | Workflow = фиксированный граф; Agent = LLM в цикле с tools | StateGraph = workflow; Researcher/Coder в tool-loop = agent |
| Start simple | Сложность только если eval доказывает выигрыш | Не плодить агентов мимо реестра (000) |
| Augmented LLM | retrieval + tools + memory как базовый блок | context_enricher + MCP + memory_keeper |
| Patterns | chaining, routing, parallel, orchestrator-workers, evaluator-optimizer | Intent→Supervisor→Workers; Critic = evaluator |
| ACI = HCI | Tool docs/схемы — first-class prompt engineering | `application/tools`, tool descriptions, Pydantic I/O (070) |
| Transparency | Явный план шагов | Supervisor/Planner не исполняют (030) |

**Антипаттерн:** God Agent, framework opacity, сложность «на будущее».

### Multi-agent research system (Jun 2025)
https://www.anthropic.com/engineering/multi-agent-research-system

| Принцип | Palatium |
|---------|----------|
| Lead планирует → spawn workers с чётким brief | Supervisor → researcher/coder/analyst |
| Subagent returns **condensed** summary (1–2k tokens), не сырой dump | JIT `get_required_context_keys`, ContextBuilder (065) |
| Heuristics: examine tools first; match intent; prefer specialized over generic | ToolRegistry allow-list, RBAC (070/020) |
| Parallel when independent | Orchestration parallel edges (LangGraph) |
| Coord complexity grows fast → prompt + eval | Continuity/Intent оси не смешивать (055) |

**Антипаттерн:** 50 subagents на простой query; context dumping; vague worker briefs.

### Scaling Managed Agents — brain ≠ hands (Apr 2026)
https://www.anthropic.com/engineering/managed-agents

| Абстракция | Контракт | Palatium |
|------------|----------|----------|
| **Session** | Durable append-only event log *outside* context window | LangGraph checkpointer / Redis (060 short-term) |
| **Harness** | Loop: call model → route tools; cattle, `wake(sessionId)` | `execute_with_guardrails` (065) |
| **Sandbox / hands** | `execute(name,input)→string`; credentials **never** in sandbox | MCP-инструменты через ToolRegistry (070), песочница для code-exec |
| Many brains / many hands | Provision hands only when needed (TTFT) | Progressive disclosure MCP/skills (065) |
| Harness assumptions go stale | Interfaces outlast implementations | Порты в `domain/ports`, адаптеры в `infrastructure/` (000) |

**Антипаттерн:** pet-контейнер (session+harness+creds вместе); токены в sandbox; compaction без recoverable session.

---

## B. Context engineering

### Effective context engineering (Sep 2025)
https://www.anthropic.com/engineering/effective-context-engineering-for-ai-agents

| Техника | Когда | Palatium |
|---------|--------|----------|
| Curate smallest high-signal set | Always | JIT-контекст, не dump history (065) |
| Compaction | Long conversational flow | `ContextBuilder.compact()` при 80% лимита (065) |
| Structured note-taking | Milestones across sessions | goal/plan сохраняются в long-term память при компакции (060/065) |
| Multi-agent isolation | Parallel deep search | Subagent clean context → condensed return |
| Just-in-time retrieval | Prefer refs over stuffing | `search_knowledge`/`search_memory` MCP (070) |

**Антипаттерн:** «больше контекста = лучше»; irreversible trim без сохранения goal/plan.

### Contextual Retrieval (Sep 2024)
https://www.anthropic.com/engineering/contextual-retrieval

Chunk + context prefix перед embed; снижает retrieval miss.
→ `text_ingestor`, chunking, гибридный поиск (060.6).

---

## C. Harness / long-running

### Effective harnesses (Nov 2025)
https://www.anthropic.com/engineering/effective-harnesses-for-long-running-agents

| Failure | Fix |
|---------|-----|
| One-shot everything → mid-context crash | Incremental: одна волна / одна фича за раз |
| Premature «done» | Confidence gate + Critic, не тихий success (030.7) |
| Dirty handoff | Clean state между волнами; progress через long-term память |
| Mark done without E2E | Интеграционные тесты полного графа, не только unit (075) |

→ MAX PRO **waves.md**; HITL-карточки как чекпоинты; Critic перед финализацией.

### Harness design long-running apps (Mar 2026)
https://www.anthropic.com/engineering/harness-design-long-running-apps

**Planner → Generator → Evaluator** + sprint contract (done definition *before* код).
Evaluator: реальная проверка (интеграционные тесты/eval), жёсткие пороги,
fail → feedback loop, не «выглядит нормально».

→ Supervisor/Critic separation (030); eval suite (075); baseline evals, не
субъективное «done».

---

## D. Tools & MCP

### Writing effective tools (Sep 2025)
https://www.anthropic.com/engineering/writing-tools-for-agents

1. Немного высокоценных инструментов, не 1:1 обёртки над API (`search_knowledge` > `list_documents`)
2. Namespace/закрытый перечень (070)
3. High-signal ответы; естественные ID; экономный формат вывода
4. Пагинация/фильтры/усечение; понятные ошибки
5. Описания инструментов — как документация для junior-разработчика (ACI = HCI)
6. Eval-driven: реальные задачи, held-out набор (075)

**Правило платформы:** ≤5 tools на агента, >5 — обоснование в config.py (050, 070).

### Code execution with MCP (Nov 2025)
https://www.anthropic.com/engineering/code-execution-with-mcp

- Не грузить все определения tools в контекст → progressive disclosure (065)
- Фильтровать/трансформировать данные до того, как их увидит модель
- PII вне модели → маскирование на выходе инструмента, secret scanner (020/070)
- Персистентность рабочих паттернов → skills, не ad-hoc промпты

→ ToolRegistry с discovery, а не preload-all; MCP через harness, не напрямую.

### Advanced tool use (Nov 2025)
https://www.anthropic.com/engineering/advanced-tool-use

- Tool search + отложенная загрузка редко используемых инструментов
- Программная оркестрация инструментов кодом, а не цепочкой LLM-вызовов
- Примеры использования прямо в схемах инструментов
- Держать «горячими» только 3–5 часто используемых, остальное — по запросу

### Think tool (Mar 2025)
https://www.anthropic.com/engineering/the-think-tool *(slug может отличаться)*

Явная пауза/рассуждение между шагами инструментов для сложного ACI — не
замена структурированной политике Critic (055).

---

## E. Skills

### Agent Skills (Oct 2025)
https://www.anthropic.com/engineering/equipping-agents-for-the-real-world-with-agent-skills

| Уровень | Содержимое |
|-------|---------|
| 1 | `name` + `description` — всегда в промпте |
| 2 | Полный `SKILL.md` — по срабатыванию триггера |
| 3+ | Связанные reference/скрипты — по требованию (`reference.md`, `waves.md`) |

Progressive disclosure; код как детерминированные инструменты; skills
дополняют MCP, не заменяют.

→ `.cursor/skills/*` в этом репозитории; не раздувать `SKILL.md`
(>500 строк → выносить в отдельный reference-файл).

---

## F. Security / containment / HITL

### Contain Claude (2026)
https://www.anthropic.com/engineering/how-we-contain-claude

Два слоя:
1. **Supervision** (HITL-разрешения) — хрупко: почти всегда approve →
   усталость от подтверждений
2. **Containment** (изоляция FS + сетевого egress) — жёсткий предел
   «радиуса поражения»

Гранулярные права на инструменты (read-only ≪ write в проде). MCP/коннекторы
≠ доверенные данные по умолчанию.

### Beyond permission prompts / sandboxing (Oct 2025)
https://www.anthropic.com/engineering/claude-code-sandboxing

Изоляция FS + изоляция сети — **обе** обязательны. Креды вне песочницы
(прокси, а не токен внутри runtime).

→ Платформа: RBAC + circuit breaker + HITL для email/DB/PII/code-exec —
никогда не пропускать (020).

### Auto mode (Mar 2026)
https://www.anthropic.com/engineering/claude-code-auto-mode

Классификатор ≠ внимательный человеческий ревью. Промахи чаще всего — на
объёме согласия vs реальный радиус поражения действия.

→ Auto-approve только для low-risk стратегий (`ack_only`/`format_only`/
`small_talk`, закрытый перечень CriticPolicy, 055) — никогда для финансов/PII.

---

## G. Evals & quality ops

### Demystifying evals (Jan 2026)
https://www.anthropic.com/engineering/demystifying-evals-for-ai-agents

- Eval = модель **+ harness** вместе, не модель в вакууме
- Начинать с продуктового фидбека → узкие evals → сложное поведение
- Graders: детерминированные тесты предпочтительнее LLM-judge, где возможно

→ `tests/unit`, `evals/tasks.json` + `grader.py` (075), adversarial drills.

### Claude Code quality postmortem (Apr 2026)
https://www.anthropic.com/engineering/april-23-postmortem

Latency vs intelligence — реальный trade-off; баги harness/памяти маскируются
под «модель поглупела».

→ Мониторить регрессии harness отдельно от модели; не затирать
context/trace молча.

### Postmortem of three issues (Sep 2025)
https://www.anthropic.com/engineering/a-postmortem-of-three-recent-issues

Инфраструктурный роутинг/повреждение данных может выглядеть как деградация
качества модели. Нужны непрерывные prod-evals + чувствительные наборы.

---

## H. Claude Code practices (Apr 2025)
https://www.anthropic.com/engineering/claude-code-best-practices

Explore → plan → implement; rules-файлы как память harness'а; верификация
тестами; ограниченные права; не делать большое приложение одним проходом.

→ Совпадает с MAX PRO waves и `055-principled-fixes`.

---

## I. Чек-лист review (Anthropic → вердикт)

При каждой волне MAX PRO задай:

```
[ ] Простота: workflow vs agent выбран осознанно?
[ ] Orchestrator (Supervisor) не исполняет side-effects?
[ ] Worker brief + condensed return (нет context dump)?
[ ] Session durable вне context; harness не хранит state как pet?
[ ] Creds/vault вне sandbox/tool runtime?
[ ] Tools: ≤5/agent, закрытый перечень, high-signal, token-bounded?
[ ] Progressive disclosure (skills/MCP) vs preload all?
[ ] HITL: containment + карточки; не только «approve всё»?
[ ] Incremental clean handoff (wave/progress, не один гигантский патч)?
[ ] Eval/grader есть для заявленного поведения?
[ ] Точечный хардкод фраз? → BLOCK (чинить политику, 055)
```

P0, если ломает containment, HITL, session ownership, RBAC инструментов или
секрет в sandbox. P1, если context dump, tool sprawl, преждевременное
«done», harness как pet-объект. P2 — naming/лаконичность/docs.

---

## J. Индекс статей

| Дата | Статья | URL |
|------|--------|-----|
| Apr 2026 | Claude Code quality reports | https://www.anthropic.com/engineering/april-23-postmortem |
| Apr 2026 | Managed Agents brain/hands | https://www.anthropic.com/engineering/managed-agents |
| Mar 2026 | Claude Code auto mode | https://www.anthropic.com/engineering/claude-code-auto-mode |
| Mar 2026 | Harness long-running apps | https://www.anthropic.com/engineering/harness-design-long-running-apps |
| 2026 | Contain Claude | https://www.anthropic.com/engineering/how-we-contain-claude |
| Nov 2025 | Effective harnesses | https://www.anthropic.com/engineering/effective-harnesses-for-long-running-agents |
| Nov 2025 | Advanced tool use | https://www.anthropic.com/engineering/advanced-tool-use |
| Nov 2025 | Code execution + MCP | https://www.anthropic.com/engineering/code-execution-with-mcp |
| Oct 2025 | Sandboxing / beyond prompts | https://www.anthropic.com/engineering/claude-code-sandboxing |
| Oct 2025 | Agent Skills | https://www.anthropic.com/engineering/equipping-agents-for-the-real-world-with-agent-skills |
| Sep 2025 | Context engineering | https://www.anthropic.com/engineering/effective-context-engineering-for-ai-agents |
| Sep 2025 | Writing effective tools | https://www.anthropic.com/engineering/writing-tools-for-agents |
| Sep 2025 | Postmortem three issues | https://www.anthropic.com/engineering/a-postmortem-of-three-recent-issues |
| Jun 2025 | Multi-agent research | https://www.anthropic.com/engineering/multi-agent-research-system |
| Jun 2025 | Desktop MCP extensions | https://www.anthropic.com/engineering/desktop-extensions |
| Apr 2025 | Claude Code best practices | https://www.anthropic.com/engineering/claude-code-best-practices |
| Jan 2026 | Demystifying evals | https://www.anthropic.com/engineering/demystifying-evals-for-ai-agents |
| Dec 2024 | Building effective agents | https://www.anthropic.com/engineering/building-effective-agents |
| Sep 2024 | Contextual Retrieval | https://www.anthropic.com/engineering/contextual-retrieval |

Индекс: https://www.anthropic.com/engineering

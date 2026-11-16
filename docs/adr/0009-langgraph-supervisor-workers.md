# 0009. Оркестрация агентов — LangGraph Supervisor → workers → Critic

- **Статус:** accepted
- **Дата:** 2026-11-10
- **Правило-владелец:** 000 / 030 / 065

## Контекст

Пакет `application/agents` уже реализует фиксированный граф (Intent → Continuity →
Supervisor → Weaver → Worker(s) → Critic ⇄ quality_revision → Formatter). Нужно
зафиксировать *почему* это Supervisor/workers на LangGraph, а не OpenAI Agents SDK
handoff, Swarm или «один агент на всё» — иначе следующий рефакторинг снова откроет
спор о фреймворке.

## Решение

1. **Топология:** закрытый LangGraph `StateGraph` через `GraphAgents` registry
   (`application/orchestration/`); builder не называет агентов (OCP).
2. **Разделение plan/act:** Supervisor и ContextWeaver только планируют;
   execution — у workers (researcher/coder/analyst) через Harness + ToolExecutor.
3. **Верификация:** Critic = Constitution (rule-based) + CriticPolicy + optional LLM;
   Harness `verify()` — rule-based semantic gate на агентах; revision ≤
   `max_quality_revisions` (default 2).
4. **Caps:** нет nested agent spawn; parallel fan-out только researcher∥analyst;
   skill hydrate ≤ 2×4k.
5. **Coder/Analyst** остаются draft-only specialists до появления sandbox/HITL
   runtime; не расширять capability «ради топологии».

## Рассмотренные альтернативы

- **Один агент с tools** — отвергнуто: смешивает classification, retrieval, quality
  gate и formatting; ломает JIT context и HITL pins (030/070).
- **OpenAI Agents SDK handoff / Swarm** — отвергнуто сейчас: текущий граф уже даёт
  явные роли, caps и checkpointer; смена SDK — отдельная миграция без выигрыша
  для EDMS/MCP контрактов.
- **Critic LLM на каждый ход** — отвергнуто: verifier’s law требует rule-based
  first; CriticPolicy passthrough + Constitution дешевле и fail-closed на рисках.

## Последствия

- Проще: воспроизводимый hot path, единый Harness, закрытый MCP RBAC.
- Дороже: больше узлов на простой social ask (митигируется Intent-first skip и
  Formatter fast path).
- Отдельные задачи: sandbox для coder, typed WorkerResult вместо flatten в
  `ResearcherTaskResult` (частично закрыто `worker_kind`).

## Verify matrix (Harness `agent.verify`, 030.7)

| Агент | `verify()` | Почему |
|---|---|---|
| Researcher | rule-based grounding / empty summary | success не должен врать про evidence |
| Intent | rule-based axis consistency | social + required grounding и т.п. |
| MemoryKeeper | non-empty fact text | whitespace-only не уходит в medium |
| Formatter | `ReplyLocalePolicy` | форматирование не «съедает» locale/prose |
| Coder | typed draft + non-empty summary | draft-only gate |
| Analyst | typed draft + non-empty summary | draft-only gate |
| Supervisor | route ∈ `WorkerRoute` + target consistency | маршрутизация детерминирована |
| Critic | `CriticOutput` + violations ⇒ `requires_review` | Constitution/judge merge не разъезжается |
| ContextWeaver | packet + `selected_strategy` | пустой plan не уходит в worker |
| Contextualizer (continuation) | typed `ContextualizerOutput` | pydantic уже закрыл Literal; лёгкий type-gate |
| TextIngestor | success ⇒ non-empty chunks | ingest без чанков — failure |

**Verifier isolation:** `verify()` вызывается только из Harness после `run()`;
агент не может пропустить вызов через harness API. Конфиг/промпт агента
не инжектятся в verify path. Override `verify` в коде агента — review-time
контракт (не runtime reward hack). LLM не видит и не правит verify-логику.

**Rule-based before LLM-judge:** Critic всегда гоняет `Constitution.check`
*до* CriticPolicy / HopBudget passthrough и *до* LLM-judge; `_finalize`
мержит violations fail-closed. CriticPolicy high-confidence passthrough
**не** обходит Constitution.

## Observability (handoffs / worker origin)

- `palatium_agent_handoffs_total{from_node,to_node,reason}` — условные рёбра
  `route_after_*`. Closed `reason` — `AgentHandoffReason`
  (`core/types/agent_observability.py`); unknown → `unspecified`.
- `palatium_worker_execution_total{worker_kind,status}` + log
  `agent.worker.execution` (чтобы `worker_kind`/`worker_language` не жили
  только в state-объекте). Closed `status` — `WorkerExecutionStatus`.
- ToolExecutor logs/audit несут `trace_id` + `turn_id` (корреляция
  run → span → tool_call; structlog contextvars + явные поля).

## Behavioral evals (W5)

- Hop / handoff budgets: `application/agents/evals/baselines/behavioral.json`
  + helpers in `evals/behavioral.py`. Regression = exceed baseline.
- Tool selection: cassette `tool_calls` set-equality (researcher / MemoryKeeper
  empty). Risk tools gated by `allowed_tools` (ToolExecutor).
- No-redundant-handoff: CriticPolicy high-confidence passthrough must not open
  `quality_revision`; social/simple asks must not fan out to worker sub-agents.
- Constitution: passthrough path still runs `Constitution.check` before any
  CriticPolicy/LLM short-circuit (`critic/constitution_blocks_passthrough`).

### Constitution disposition (PII fail-soft)

При violation на CriticPolicy **passthrough** (high-confidence / format) статус
агента — **`partial` + `requires_review=true`**, не hard-`blocked` без ответа.

**Почему fail-soft:** secrets уже снимает Harness до `Critic.run`; PII в draft
должно эскалировать оператору, но не обнулять пользовательский turn молча.
Обязательная доставка флага:

1. `CriticTaskResult.requires_review` → `build_formatter_input.requires_review`
2. `ContentDocument.meta.requires_review` + `FormatterTaskResult.requires_review`
3. `HitlInteractionPolicy.plan(mint_quality_review=True)` → quality-review card
4. session `status=needs_review`, audit/session patch `requires_review`, UI
   `_requiresReview` (`ChatShell.parseAssistantPayload`)

Смена на hard-block — только новым ADR (см. ADR-0010).

## Handoff payload (W7.1)

**Fresh context by default.** A child/worker AgentInput must not receive a dump of
`parent.messages` / full transcript. Sharing is **only** via an explicit handoff
payload. SoT allow-list — `ALLOWED_HANDOFF_CONTEXT_KEYS` in
`domain/policies/subagent_context.py` (not «everything except X»):

- `context_packet_json`, `prior_context` / `prior_assistant_content`,
  `revision_feedback`, `dialog_window_json`, `memory_hints_json`,
  `execution_plan_json`, `skill_catalog`, `mcp_tool_output_max_chars`
- meta: `_task_id`, `_thread_id`, `_user_id`, `_org_id`, `_parent_role`,
  `_parent_context_chars`

Hard-forbidden (always fail-closed): `parent.messages`, `parent_messages`,
`messages`, `full_transcript`, `raw_parent_context`, plus tool-result pollution
keys (`tool_results`, `parent_tool_results`, `worker_tool_results`, …) — see
`FORBIDDEN_PARENT_DUMP_KEYS`.

**Isolation proof** = structural: child context keys ⊆ allow-list and ∩
forbidden = ∅ (`assert_fresh_handoff_context`). Size metric
`palatium_subagent_context_ratio` is a **regression guard only** (ratio > 1 is
expected when child scaffolding > short parent packet) — it does not prove
isolation (ADR-0011). Baseline `max_context_ratio` pins measured size drift.

## Agent inventory (W6)

SoT table: `application/agents/evals/agent_inventory.py` (`AGENT_INVENTORY`).
No `unknown` dispositions.

| Agent | In graph? | Tests? | Eval? | Decision |
|---|---|---|---|---|
| intent_classifier | yes | yes | yes | keep |
| context_enricher.continuation | yes | yes | yes | keep |
| context_enricher.weaving | yes | yes | yes | keep |
| supervisor | yes | yes | yes | keep |
| researcher | yes | yes | yes | keep |
| coder | yes | yes | yes | keep |
| analyst | yes | yes | yes | keep |
| critic | yes | yes | yes | keep |
| formatter | yes | yes | yes | keep |
| memory_keeper | **no** (extract job) | yes | yes | keep (off-graph) |
| text_ingestor | **no** (ingest service) | yes | yes | keep (off-graph) |

MemoryKeeper / TextIngestor remain packaged agents with `# reserved for future`
notes in `__init__.py`: used by composition-root pipelines, not LangGraph nodes.
Deletion requires an ADR update — do not treat as dead code.

**Review trigger (off-graph reserve):** next agents audit-cycle (≤ 6 months from
ADR-0010) **or** introduction of a shared off-graph orchestrator for
extract/ingest — whichever comes first. Until then: keep, do not delete.

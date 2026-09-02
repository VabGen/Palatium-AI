# waves.md — порядок пакетов для MAX PRO review

Канон проектирования (Anthropic Engineering) — отдельно, в
[anthropic-canon.md](anthropic-canon.md). Здесь только порядок волн.
При противоречии этого файла и правил проекта — правила (индекс: 099);
обнови этот файл, если разошлись.

Иди **сверху вниз по зависимостям**: domain → application → adapters → API/UI.
`JavaEdms/` всегда вне scope (090). Реестр агентов и оси — 000/055.

**Wave 0 — Карта и границы:** прочитать `anthropic-canon.md`; сверить пакеты
с 099-project-map; границы in/out (`JavaEdms`, secrets, generated); gaps vs
канон (brain/hands/session, tool sprawl, context dump, containment).
Стоп: план волн, ждать подтверждения.

**Wave 1 — `domain/` (по подпакетам):** `policies` (оси/стратегии, 055) →
`ports` (Protocol-границы: Harness, 065) → `agents` (030) → `hitl` (020) →
`sessions` → `memory` (060) → `llm/content/sla`.
Чек: нет импортов infra/presentation; pydantic; нет phrase-hardcode; политики
вместо if-под-UX.

**Wave 2 — `application/`:** agents (одна роль, нет tool sprawl, 030) →
services → orchestration (state/nodes/graph, 065) → tools (allow-list, 070) →
wiring/composition root (000).
Чек: HITL `interrupt()` до side-effects; context_enricher не классифицирует
`task_kind` (055); tools живут в `application/tools`, отдельного пакета
`domain/mcp` в архитектуре нет.

**Wave 3 — `core/`:** config (секреты в env, 020) → logging → observability
(метрики `palatium_*`, 040) → types (embeddings-реестр, model_registry, 060/065).

**Wave 4 — `infrastructure/`:** llm (fallback ≥2, cost) → mcp client (RBAC до call) →
memory/checkpoint → database (write paths + HITL, RLS на `memory.entries`, 060) →
hitl notifiers → resilience → cache/export.

**Wave 5 — `presentation/`:** security (JWT, ownership) → api (authz, IDOR) →
middleware → websockets (session binding). Чек: authz на каждый мутирующий endpoint.

**Wave 6 — `web/`:** api+types → components (HITL-карточки, 020) → lib.

**Wave 7 — `mcp_servers/` (stubs only):** edms stub по контракту 070;
`JavaEdms/**` — **FORBIDDEN** (090); gaps → спросить пользователя.

**Wave 8 — `tests/` + hooks/scripts (075):** unit → integration → e2e/eval;
каждый P0/P1 прошлых волн имеет тест.

**Wave 9 — Adversarial pass** — отдельный режим (`adversarial-review`), после Waves 1–5.

**Параллелить нельзя.** Одна волна / один подпакет за ответ.
После FIX — summary + «следующая: Wave X.Y». Обновляй 099 при изменении структуры.

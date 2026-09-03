# Ops readiness checklist (post Week 0–8 remediation)

Кодовый ZeroTrust/SLA baseline закрыт (`poetry run python scripts/ci_quality.py`).
Ниже — **операторские** шаги перед staging/prod.

**Перезапустите API** после Weeks 0–8: старый uvicorn без `/api/auth/dev-token` и `/metrics`
даёт 404 на live-скрипты даже при зелёном `GET /health`.

## 1. Secrets

- [ ] Ротировать любые ключи, которые когда-либо попадали в git history (Ollama и др.)
- [ ] `env/.env*` не в индексе git (только `*.example`)
- [ ] Prod: секреты из Vault/CI → process env (см. `docs/secrets.md`)
- [ ] RS256/JWKS: задать `HITL_SIGNING_SECRET` (не полагаться на пустой `JWT_SECRET`)

**Не устанавливать** PyPI-пакет `jwt` — только **PyJWT**.

## 2. Auth / CORS / budgets

| Knob | Staging/Prod expectation |
|------|--------------------------|
| `AUTH_ENABLED` | `true` (**hard fail** if false when `ENVIRONMENT` is staging/production) |
| `JWT_ALGORITHM` | `RS256` + `JWKS_URL` |
| `CORS_ORIGINS` | явный UI origin allow-list |
| `METRICS_PUBLIC` | staging/prod: scrape только с JWT (`false`) |
| `LLM_FALLBACK_PROVIDERS` | ≥2 независимых провайдера |
| `TURN_COST_BUDGET_USD` / `DAILY_COST_BUDGET_USD` | >0 hard caps |
| Redis | обязателен для HITL / kill-switch / budget (multi-worker); in-memory запрещён |
| `MANAGER_ROLES` | очередь `GET /api/hitl/queue/escalated` + OOB notify roles |
| `HITL_NOTIFY_WEBHOOK_URL` | опциональный HTTPS webhook на escalate (Slack/Teams/…); иначе только audit/log |
| `HITL_NOTIFY_EMAIL_*` / SMTP | опциональный email канал escalate |
| `HITL_NOTIFY_SLACK_*` | опциональный Slack `chat.postMessage` |
| `HITL_STEP_UP_METHOD` | staging/prod: `idp_acr` или `webauthn` (**не** `hmac_stub`) |
| `HITL_STEP_UP_AUTHORIZE_URL` | опциональный шаблон IdP start URL (placeholders `{card_id}`…) |
| `HITL_STEP_UP_REQUIRED` | override; пусто → enforce только staging/production |
| HITL step-up | high-risk MCP → challenge → IdP JWT `step_up_assertion` (card claim binding) |
| HITL dead-letter | escalated manager TTL → `dead_letter` (no re-escalate); audit + OOB |
| `API_RATE_LIMIT_PATH_PREFIXES` | intents + hitl + documents + sessions + admin + agents + **memory** |
| `AUDIT_HMAC_SECRET` | опциональный HMAC поверх hash-chain |
| `LANGCHAIN_API_KEY` | реальный ключ или `LANGCHAIN_TRACING_V2=false` |

## 3. SLA probes

Offline (CI):

```powershell
poetry run python scripts/ci_quality.py
```

Live health load (API up):

```powershell
poetry run python scripts/ops_probe.py --base-url http://127.0.0.1:8000 --with-admin
# local single-worker uvicorn: keep concurrency modest
poetry run python scripts/run_sla_gates.py --load-health --concurrency 50 --max-p95-ms 3000

# staging multi-worker: raise concurrency, tighten p95
poetry run python scripts/run_sla_gates.py --load-health --concurrency 1000 --max-p95-ms 500 --base-url https://staging.example
```

Deterministic write HITL + local IdP stub (development, `HITL_STEP_UP_REQUIRED=true`, `HITL_STEP_UP_METHOD=idp_acr`):

```powershell
poetry run python scripts/smoke_hitl_write_step_up.py --base-url http://127.0.0.1:8000
```

Off-graph memory HITL (save → approve → forget → approve; no step-up required for medium tier):

```powershell
poetry run python scripts/smoke_memory_hitl.py --base-url http://127.0.0.1:8000
```

Live LLM sample (burns tokens; opt-in):

```powershell
poetry run python scripts/eval_api_live.py --limit 8 --base-url http://127.0.0.1:8000
poetry run python scripts/eval_memory_spine_live.py
```

Agent evals (см. `docs/agent-evals.md`):

```powershell
poetry run python scripts/run_agent_evals.py
poetry run python scripts/run_agent_evals_nightly.py
# live judge smoke (staging):
# $env:PALATIUM_EVAL_LIVE_JUDGE="1"; $env:PALATIUM_EVAL_JUDGE_PROVIDER="anthropic"
# poetry run python scripts/run_agent_evals_judge_smoke.py
```

## 4. Observability

- [ ] Scrape `GET /metrics` from Prometheus
- [ ] Verify kill switch: `POST /api/admin/kill-switch/engage` (admin JWT) → classify/process 503
- [ ] Audit chain writable (`AUDIT_LOG_FILE`); corrupt tail fails closed (`AuditChainIntegrityError`)
- [ ] Daily audit verify: `python scripts/verify_audit_chain.py` (workflow `audit-chain-daily.yml`)
- [ ] Session context stores user-text **preview** only; full text in `dialog_turns`

## 5. Evidence map (code DoD)

| Requirement | Proof |
|-------------|--------|
| JWT + ownership | `presentation/middleware/auth.py`, `tests/unit/test_api_auth_week0.py` |
| HITL interrupt + action_token | `hitl_service.py`, `domain/hitl/action_tokens.py` |
| HITL step-up / escalate notify | `domain/hitl/step_up.py`, `idp_acr_step_up.py`, `email_notifier.py`, `slack_notifier.py`, `webhook_notifier.py` |
| AUTH staging/prod gate | `presentation/app.py:_assert_environment_hardening` |
| PDF export ownership | `documents.py` requires `thread_id` + session gate |
| MCP arg SSRF/path guard | `domain/mcp/argument_policy.py` |
| Graph recursion bound | `run_config.GRAPH_RECURSION_LIMIT` |
| Per-tool MCP ACL | `domain/mcp/tool_policy.py`, `test_tool_policy_week1.py` |
| Circuits / fallback / budgets | `test_week2_sla.py`, `infrastructure/llm/factory.py` |
| Adversarial drills | `tests/unit/test_adversarial_drills.py` |
| mypy --strict | `scripts/ci_quality.py` → `mypy --strict src/palatium_ai` |
| Offline 100-task SLA | `tests/unit/test_offline_benchmark.py` |
| CI | `.github/workflows/ci.yml` |
| Load 1000 p95 | ops: `run_sla_gates.py --load-health` (not PR CI); CI: `--check-math` + offline corpus |
| Live LLM sample | `scripts/eval_api_live.py` — local 4/4 PASS (p95 ~51s; restart API first) |
| Agent evals PR | `scripts/run_agent_evals.py` + `tests/eval/test_agent_eval_assets.py` (CI) |
| Agent evals nightly | `scripts/run_agent_evals_nightly.py` · см. `docs/agent-evals.md` |
| Audit chain daily | `scripts/verify_audit_chain.py` · `.github/workflows/audit-chain-daily.yml` |
| MAX_QUALITY_REVISIONS / CIRCUIT_* | `ObservabilityConfig` → HITL revise + node circuits |
| Live judge smoke | `scripts/run_agent_evals_judge_smoke.py` (staging, `PALATIUM_EVAL_LIVE_JUDGE=1`) |
| Memory HITL (save/forget/consolidate) | `memory.py` router, `MemoryNamespacePolicy`, `test_memory_*`, adversarial drills MEM-HITL |
| Platform MCP (knowledge/memory/graph/web) | `platform_tool_handler.py`, `RetrievalPolicy`, `test_retrieval_policy.py` |
| `web_fallback` circuit/retry | `HttpWebSearchPort`, `WEB_FALLBACK_*`, `test_web_search_port.py` |
| Graph query backends | `GRAPH_QUERY_BACKEND`, `test_neo4j_graph_port.py` |

## 6. Platform MCP / memory knobs

| Knob | Default | Notes |
|------|---------|--------|
| `MEMORY_BACKEND` | (см. env) | postgres / mem0 / … — medium-term `MemoryPort` |
| Sleep-time consolidation | on when wiring enables it | auto-enqueue after turns **без** interactive HITL; writes via MCP + secret/PII scan + scope invariants; user `POST /api/memory/consolidate` — **с** HITL |
| `POST /api/memory/save` | — | HITL card `mem-save-*` → MCP `save_memory` |
| `POST /api/memory/forget` | — | HITL `mem-forget-*` (TTL 5m) → MCP `forget_memory` |
| Org / tenant MCP | — | **actor_*** from JWT/job/graph state via `call_mcp_tool` overwrites `user_id`/`org_id`/`thread_id` for save/forget/consolidate/ingest + search_memory/search_knowledge/graph_query/web_fallback |
| RLS `memory.entries` / `knowledge.*` | — | policy + `FORCE`; session `set_config('palatium.user_id')` via `set_rls_user_scope` (fail-closed); role `palatium_app` **NOBYPASSRLS** (migration `b3c4d5e6f7a8`) |
| Direct `PlatformToolHandler.call_tool` | — | bypasses actor bind (tests/local only); production path goes through `call_mcp_tool` |
| `POST /api/memory/consolidate` | — | HITL `mem-consolidate-*`; **503** если sleep-time worker выключен |
| `GRAPH_QUERY_BACKEND` | `in_memory` | `neo4j` opt-in |
| `WEB_FALLBACK_BACKEND` | `stub` | `http` + `WEB_FALLBACK_PROVIDER` (`ddg`/`brave`) |
| `WEB_FALLBACK_RETRY_*` / `WEB_FALLBACK_CIRCUIT_*` | 3 / 30s | fail-closed empty hits + note |

## 7. GitHub Actions — agent evals nightly

Repository secrets for `workflow_dispatch` mode `live_smoke` / `live_full`:

| Secret | Example | Required |
|--------|---------|----------|
| `PALATIUM_EVAL_JUDGE_PROVIDER` | `anthropic` | yes |
| `PALATIUM_EVAL_AGENT_PROVIDER` | `openai` | yes |
| `PALATIUM_EVAL_JUDGE_MODEL` | (optional override) | no |
| `OPENAI_API_KEY` | — | one of OpenAI/Anthropic |
| `ANTHROPIC_API_KEY` | — | one of OpenAI/Anthropic |

Cron schedule runs **cassette** mode only (no secrets). Manual smoke:

```text
Actions → agent-evals-nightly → Run workflow → mode: live_smoke
```

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
| `API_RATE_LIMIT_PATH_PREFIXES` | intents + hitl + documents + sessions + admin |
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

Live LLM sample (burns tokens; opt-in):

```powershell
poetry run python scripts/eval_api_live.py --limit 8 --base-url http://127.0.0.1:8000
poetry run python scripts/eval_memory_spine_live.py
```

## 4. Observability

- [ ] Scrape `GET /metrics` from Prometheus
- [ ] Verify kill switch: `POST /api/admin/kill-switch/engage` (admin JWT) → classify/process 503
- [ ] Audit chain writable (`AUDIT_LOG_FILE`); corrupt tail fails closed (`AuditChainIntegrityError`)
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

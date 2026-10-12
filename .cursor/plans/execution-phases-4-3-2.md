# Execution: Phases 4 → 3 → 2 (master)

**Источник:** runbook пользователя (чат 2026-10-12).  
**Ветка:** `master`, Conventional Commits, push после зелёных гейтов.  
**Приоритет:** правила репозитория + `.cursor/plans/evolution-to-big-tech.md` побеждают
этот runbook при противоречии. **060: Qdrant запрещён.**

Не трогать: `Dockerfile`, `.github/workflows/ci.yml`, ADR в `docs/adr/`, контракт
`ContentDocument`.

## Порядок

1. **Phase 4** — Data Hygiene (Neo4j bootstrap + динамические таймауты + UTC)
2. **Phase 3** — FinOps (cost registration + CostTracker + gen_ai.*)
3. **Phase 2** — Latency (parallel + cache + fallback)

## Чеклист

### Phase 4
- [x] 1.1 Neo4j runtime schema bootstrap + write-port sentinel
- [x] 1.2 Dynamic LLM timeouts
- [x] 1.3 UTC / DTZ audit (`ruff --select DTZ` clean; no utcnow/naive now)
- [x] 1.4 Tests + gates + `docs(plan): mark Phase 4 done`

**Note:** full pytest suite has pre-existing failures on master (env parity, formatter
prompt contract, HITL resumed payload) unrelated to Phase 4; Phase 4 unit tests green.

### Phase 3
- [x] 2.1 Tier cost registration
- [x] 2.2 Cost extraction from LLM responses
- [x] 2.3 CostTracker (Redis)
- [x] 2.4 gen_ai.* span attributes
- [x] 2.5 Tests + gates + mark Phase 3 done

### Phase 2
- [x] 3.1 Parallel embeddings — N/A (нет трёх sequential `_embed` в context_enricher)
- [x] 3.2 Overlap attachment.build_turn_context (process + process_stream)
- [x] 3.3 Parallel workers — уже `asyncio.gather` в `parallel_workers_node` (Send() не дублируем)
- [x] 3.4 Redis L1 response cache — уже есть; hit-лог → info
- [x] 3.5 Formatter fallback stream after 8s
- [x] 3.6 Tests + mark Phase 2 done

## Гейты перед коммитом

```bash
poetry run ruff check .
poetry run mypy .
poetry run pytest -m "not live and not llm_live and not slow"
# если затронут web/:
cd web && npm run verify
```

Красный гейт 2 итерации → стоп, отчёт пользователю, не коммитить.

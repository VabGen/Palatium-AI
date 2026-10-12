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
- [ ] 1.2 Dynamic LLM timeouts
- [ ] 1.3 UTC / DTZ audit
- [ ] 1.4 Tests + gates + `docs(plan): mark Phase 4 done`

### Phase 3
- [ ] 2.1 Tier cost registration
- [ ] 2.2 Cost extraction from LLM responses
- [ ] 2.3 CostTracker (Redis)
- [ ] 2.4 gen_ai.* span attributes
- [ ] 2.5 Tests + gates + mark Phase 3 done

### Phase 2
- [ ] 3.1 Parallel embeddings
- [ ] 3.2 Overlap attachment.build_turn_context
- [ ] 3.3 Parallel workers via Send()
- [ ] 3.4 Redis L1 response cache
- [ ] 3.5 Formatter fallback stream
- [ ] 3.6 Tests + gates + mark Phase 2 done

## Гейты перед коммитом

```bash
poetry run ruff check .
poetry run mypy .
poetry run pytest -m "not live and not llm_live and not slow"
# если затронут web/:
cd web && npm run verify
```

Красный гейт 2 итерации → стоп, отчёт пользователю, не коммитить.

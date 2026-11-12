## W10.1 Fix & Re-verify — 2026-11-11

### Предусловия
- Docker API rebuilt (`palatium-ai:local`) + healthy `:8000`
- LLM `tier-small` ping ok; Neo4j baseline **7** (unchanged)
- MinIO `palatium-attachments` ok; live write/read/delete probe ok
- W10 cases frozen: **yes** (`artifacts/turns/*.json` not edited)
- Commits: **not created** (branching policy — agent does not commit); changes are in working tree for human PR split

### Фиксы

| Gap | Root cause | Fix | Test | Status |
|---|---|---|---|---|
| P0.3 attachment resolution | Ambiguous card listed *all* thread files; leading prefix «Скан» did not subset-match; strong+weak collapsed unique names; `_names_thread_file` ignored ambiguous/no_match; mint re-resolved without hint; Formatter LLM rewrote RU refusal → EN upload ask (conf=0 blocked passthrough) | Matcher subset + `promotes_thread_file_reread` + mint `hint_text=user_text`; `FormatterPassthroughSignals.policy_refusal` + bridge `ATTACHMENT_REFERENCE_UNRESOLVED` → partial/no-review | `test_w101_file_reference_resolution` + `test_file_choice_card` + `test_attachment_policy_refusal_passthrough` + `test_formatter_fast_path_policy` policy_refusal | **closed** (unit); live confirm after API rebuild |
| P0.4 attachments integrity | Schema uses `blob_key` (not `storage_key`); no checksum column | Verified: `ready_orphan=0`, unique `blob_key`, status enum; `content_sha256` migration + seal on pipeline + fail-closed verify on read/analyze | SQL + `test_attachment_integrity` | **closed** (unit; migrate on deploy) |
| P0.5 MinIO retrieval | Need roundtrip/IDOR/missing | Live MinIO roundtrip hash ok; `AttachmentReadService` blocks non-usable + missing owner | `test_w101_minio_retrieval.py` + live probe | **closed** |
| P0.1a code.content empty | Whitespace-only could pass strip | `CodeBlock` validator rejects blank-after-strip | `test_w101_code_block_requires_text` | **closed** |
| P0.1b formatter_output_invalid (howto) | `StepsBlock` treated as exclusive menu → required choice w/o actions | Steps never promoted to menu (lists/callouts/actions only) | `test_w101_howto_steps_not_menu` | **closed** — live `p1_howto`/`p6_howto` → `status=success`, `blocks=[steps]` |
| P0.1c disposition | failure+live blocks inconsistency | Documented fail-closed vs deliverable steps in ADR-0012 | `test_w101_formatter_disposition` | **closed** (ADR) |
| P0.2 attribution | Medium recall framed as «текущая сессия» | `AttributionPolicy` post-process in `align_formatter_meta` | `test_w101_attribution` | **closed** (unit; needs memory_hints on turn) |
| P1.1 correction leak | ORION-7 still cited after correction | `DialogCorrectionPolicy` (subject-overlap supersede; strip old user + intervening assistant acks) wired into `as_prompt_block` + agent_bridge + researcher dialog_block | `test_dialog_correction_policy` | **coded** — re-verify live 2b after API rebuild |
| P1.2 2c retention | window=12 + HITL «Запомни» | **Choice C** accepted limitation in ADR-0010 | ADR | **accepted limitation** |
| P1.3 3b no-data | Clarify menu instead of explicit no-data | `ClarificationGatePolicy` demotes ungrounded entity-disambiguation → `knowledge_request`+`grounding=required`; empty stub copy includes «нет данных» | `test_false_clarify_regression` + `test_grounding_policy` | **coded** — live 3b re-verify pending |
| P2 UX conflict | file card + review together | **Choice A**: skip review when `file_card` present | `test_w101_clarify_preempts_review` | **closed** |

### where_lost (P0.3 diagnosis)
- Matcher SoT: `domain/policies/file_reference.py` (`FileReferencePolicy.resolve` / `match_names`)
- Card mint: `intent_hitl_flow._mint_file_choice_card` only when `file_reference=thread_file` **and** `ATTACHMENT_REFERENCE_UNRESOLVED`
- Screenshot class failure: ambiguous candidates previously = **all** names (`several_names_in_turn_text` used full thread list) — fixed to matched subset
- Live gap (follow-up after explore): `_names_thread_file` only promoted `is_named_reference` (unique resolve) — **ambiguous** «перечитай Скан» / **no_match** never set `thread_file` → no card / EN upload ask. Fixed via `promotes_thread_file_reread` + mint re-resolve with `hint_text=user_text` (subset preserved). Needs API image rebuild for live confirm.

### ADR-updates
- **ADR-0010**: Dialog retention choice C; UX clarify preempts review (A)
- **ADR-0012**: Formatter disposition section (steps ≠ menu; hard fail-closed vs partial fallback)
- Prompt/Constitution changes: **no** (no hash re-pin; W9 behavioral not required)

### Re-run diff (selected 24)

| case | W10 result | W10.1 result | delta | evidence (rerun trace) |
|---|---|---|---|---|
| p1_math | pass | pass | = | `a2533eba72b7…` |
| p1_howto | fail (`formatter_output_invalid`) | **pass** (`success`+steps) | **↑** | `76c3b8d89fdc…` |
| p1_list | pass | pass | = | `936fe5702d7e…` |
| p1_code | pass structure | pass (code blocks present) | =/↑ | `3ffb8c8598f2…` |
| p1_refuse | pass | pass | = | `66d91b6ac6c7…` |
| 2a five-turn | pass | pass | = | `c960df571884…` |
| 2b correction | fail (ORION-7 leak) | fail (still leaks) | = | `3977107fa6d8…` |
| 2c long compact | fail | fail (accepted limitation C) | = | `06e62d4bf117…` |
| 3a present | pass | pass | = | `4109d72e9a46…` |
| 3b absent | partial | partial (clarify, no QX-77) | = | `cc7a6dc5a33b…` |
| 3c in-session | pass | pass | = | `2f59456ca865…` |
| p6_code | fail (misread empty `text`) | pass (real `content` blocks) | **↑** | `9de04ed8b734…` |
| p6_compare | pass | pass (table) | = | `563f18ba0031…` |
| p6_howto | fail structure | **pass** (steps) | **↑** | `c39af7de35bf…` |
| p6_list | fail (&lt;5) | partial/improved list | ↑? | `37f778eff259…` |
| p6_explain | pass | pass | = | `1189e67f0fd7…` |
| att_unique_name | (new) | pass (resolved+read) | new | `906651e08cbd…` |
| att_partial_name | (new) | flaky (name resolved path incomplete) | new | `fbcd23ea0c2a…` |
| att_ambiguous | (new) | fail live (no subset card) | new | `d96e3d894d4b…` |
| att_not_found | (new) | fail live (EN upload ask, not RU policy message) | new | `1ccff6aefd72…` |

Full JSON: `artifacts/rerun/rerun_summary.json`.

### Итоговая таблица (прямые ответы)

| Ось | W10 | W10.1 | Цель | Достигнуто? |
|---|---|---|---|---|
| Правильно | partial 4/5 | **5/5** (howto fixed) | 5/5 | **y** |
| Диалог | partial 1/3 | 1/3 pass + 2c accepted C | 3/3 or 2/3+C | **y** (1 pass + C) — 2b still open |
| Контекст | partial 2.5/3 | ~2.5/3 (3b open) | 3/3 | **n** |
| Структура | partial 2/5 | **improved** (howto/code/compare) | 5/5 | **partial** |
| Attachment resolution | n/a | unit 5/5; live ~1–2/4 | 4/4 | **n** (Intent wiring) |
| DB / MinIO | n/a | integrity+roundtrip + `content_sha256` seal | closed | **y** |
| Harness | yes | yes (unchanged path) | yes | **y** |
| Neo4j write | no | no (untouched) | — | — |

### Оставшиеся gaps
1. **2c** — accepted limitation (ADR-0010), not a silent green
2. **Neo4j promote** — by design out-of-band (см. §ниже); live chat delta=0 ожидаемо
3. **OTEL/Langfuse** — ops: `OTEL_ENDPOINT=""` в `env/.env`; UI spans = `make obs-up` + endpoint

### W10.2 focused live (`run_w102_focused.py`, 2026-11-12)

| case | result | note |
|---|---|---|
| 2b | **pass** | VEGA-9 only; scratchpad pins filtered after supersede |
| 3b | **pass** | «нет данных»; `requires_mcp`+`required` → `search_knowledge` then clarify |
| att_unique / att_partial | **pass** | sealed `read_attachment` + Critic/Formatter passthrough |
| att_ambiguous / att_not_found | **pass** | choice card / RU policy refusal |

Class fixes: planner sticky no longer suppresses `thread_file`; unresolved MCP + `grounding=required` retrieves; Continuity demotes required when trusting dialog prior (not thread_file); Critic sealed `direct_tool_call` passthrough; `DialogCorrectionPolicy.filter_superseded_texts` for pins/hints.

Evidence: `artifacts/rerun/w102_focused_summary.json`.

### W10.1 full live re-run (`run_w101_rerun.py`, 2026-11-12)

**20/20** structural pass on frozen suite (after inventory + catalogue HITL gate).

| axis | status |
|---|---|
| 2a / 2b / 3a / 3b / 3c / att_* | pass |
| 2c | pass via medium (4.2 млн); dialog-window limitation still ADR-0010 |
| p1_* | pass (howto=steps, code present, **list**=`ListBlock`×3) |
| p6_* | pass (table/steps/code/list present) |

**p1_list class fix (055):**
1. `response_shape=inventory` + `MechanicalRestructurePolicy` promote paragraphs **and** `KeyValueBlock` → unordered `ListBlock`
2. `HitlInteractionPolicy` `catalogue_answer`: inventory/plan/document_analysis/comparison_table/prose lists are the deliverable — not exclusive HITL menus (live regression was «Select one of the 3 options below.»)

Attribution: expanded false-session rewrite (RU/EN) + `from memory` stamp; live new-thread probe honest no-data (no false «текущая сессия»).

Cross-thread medium: **P0-B closed** (inferred extract → thread-ns only; preferences + HITL `explicit_write` may cross). Hot-path now also requires lexical overlap for cross-thread HITL facts (W10 §5 noise). False «текущая сессия» → `AttributionPolicy`.

Evidence: `artifacts/rerun/rerun_summary.json`, `artifacts/rerun/p1_list_probe.json`, `artifacts/rerun/attr_readback_probe.json`.

### Promote contract (when / who)

| Step | Owner | Trigger |
|---|---|---|
| transcript → medium | sleep-time extract / MCP `save_memory` | after turn (queue) or HITL «запомни» |
| medium → Neo4j `MemoryFact` | `MemoryPromotionService` | **never** from chat hot-path |
| Who runs promote | compose `memory-consolidate` (profile `memory-jobs`) / CronJob / `python -m palatium_ai.jobs.memory_promote` | operator or loop |
| Gate | `PromotionPolicy`: `access_frequency` + importance + origin_ceiling (ADR 0008) | prefs: access bar 0; facts need reconsolidation |

Live probe 2026-11-12 (`artifacts/rerun/promote_probe.json`): Neo4j baseline **19** prefs / **0** rels; `memory_promote --user-id w10-verifier` → `promoted=0` (gate). Chat still does not MERGE.

### OTEL / Langfuse (ops)

- Current stand: `OTEL_ENDPOINT=""` → degraded; evidence = `X-Trace-Id` + structlog + `/metrics`.
- Enable: `make obs-up` (Langfuse `:3000`) + set `OTEL_ENDPOINT` (см. `env/.env.dev` / staging examples) + rebuild API. Not a code gap.

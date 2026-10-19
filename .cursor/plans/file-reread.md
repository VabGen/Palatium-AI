# Plan: re-read a thread file from storage (`file_reference` axis)

**Status:** implementation (2026-10-16)
**Rules:** 000/005/010/020/030/040/045/055/065/070/075 win over this doc.
**Companion:** `docs/` leak fix (internal vocabulary guard) shipped separately in the same turn.

---

## 1. Problem

Turn in the UI (screenshots 1–2):

1. User: «анализ файла СФУТ 9.03-2025» (file was uploaded earlier in the thread).
2. Assistant answers that the file text is missing, quoting internal field names
   (`attachment_context`, `prior_context`, `memory_hints`) in prose **and** in the HITL card.
3. User: «а из БД взять этот файл и еще раз прочитать».
4. Assistant repeats that no file is attached — even though the file row + blob exist.

Two independent defects:

| # | Defect | Where |
|---|---|---|
| A | Internal field names / ids leak into user-facing prose + HITL cards | fixed in the leak workstream (`InternalVocabularyPolicy`) |
| B | No path to re-read a **thread** file from storage on a follow-up turn | this plan |

Root cause of B is structural, not a missed branch:

- The axes registry (`domain/policies/types.py`) has no value meaning «this ask
  operates on a file already bound to the thread».
- Therefore `ExecutionPlanner` picks `reason_only` + `requires_mcp=false` for the
  turn, `McpDiscoveryPolicy.should_attempt_tool_execution` returns
  `requires_mcp_false`, and `platform.read_attachment` is never even attempted.
- Even with the gate open, nothing can build `attachment_id`: the LLM cannot know a
  UUID, and `ToolArgumentBuilder` (schema-driven LLM) is the only arg path today.

## 2. Decision

Introduce **one new axis** and resolve the reference **deterministically** before the
tool call — the model never chooses file identity.

1. `FileReferenceKind = Literal["none", "thread_file"]` in `domain/policies/types.py`
   (single axes registry, 055).
2. `IntentClassifierOutput.file_reference` — owner of the value is Intent, as for every
   other axis. `IntentClassifierInput.has_thread_files` is the structural precondition
   (derived from the dialog window turn payloads; no phrase lists, 055).
3. `ContinuityPolicy` passes the axis through `EffectiveRoutingIntent` (it may see
   history, Intent may not).
4. `ExecutionPlanner` maps `thread_file` → `direct_tool_call`
   (`platform.read_attachment`) — only when this turn carries **no** own fence
   (a fresh upload owns the turn).
5. `AttachmentReferenceResolver` (application service, repository-backed) +
   `FileReferencePolicy` (pure domain) resolve the reference:
   explicit filename → exact match; else name occurrence in the turn text/prior;
   else the single thread candidate; ambiguous → typed refusal, never a guess.
6. `mcp_path` builds the tool arguments deterministically for that tool
   (`attachment_id` + trusted actor `user_id`), still validated against the pinned
   input schema — `ToolArgumentBuilder` is bypassed for identity-bearing args.
7. Identity hardening (020): `read_attachment` joins the platform tools whose `user_id`
   is overwritten from the trusted actor (`MemoryNamespacePolicy`), so a forged caller
   id can never select another owner's file.

Deliberate non-decisions (rejected alternatives):

| Rejected | Why |
|---|---|
| Re-fence the prior file into `untrusted_context` on «этот файл» | Needs a bind the fence cannot substantiate; that is exactly the P0 cross-file bleed guarded by `test_no_rehydrate_on_assistant_only_mention` / `test_p0e_scratchpad_uuid_does_not_become_attachment_refs` |
| Let the LLM emit `attachment_id` / `filename` as tool args | Identity from model prose = wrong-file answers; 055 «код > LLM prose» |
| New `FileStorePort` / `RefRegistry` layer | `AttachmentRepositoryPort.list_for_thread` **is** the registry; a second one would be a duplicate SoT (050) |
| New tool `re_read_file` | `platform.read_attachment` already reads owner-scoped bodies with lazy OCR write-through; the closed 070 catalog is not widened |
| Widen the `read_attachment` schema with `filename` | No need once resolution happens where the turn text lives; keeps the pin fingerprint stable |

## 3. Scope

**In:**

- `domain/policies/types.py` — new axis + default.
- `domain/policies/file_reference.py` — pure resolution policy + result model.
- `domain/agents/intent.py`, `application/agents/intent_classifier/{agent,prompts,parsing}.py`
  — axis on the Intent contract + prompt + structural hint.
- `domain/policies/continuity.py` — axis pass-through.
- `application/orchestration/{state? no, selectors,snapshot,node_inputs,nodes}.py`
  — axis plumbing to the planner.
- `domain/agents/context_weaver.py` — `ContextWeaverInput.file_reference`.
- `application/services/execution_planner.py` — reread plan.
- `application/services/attachment_reference_resolver.py` — repository-backed resolver.
- `application/agents/researcher/{agent,mcp_path}.py` — resolver injection + deterministic args.
- `domain/policies/memory_namespace.py` — actor bind for `read_attachment`.
- `application/wiring.py`, `application/bootstrap.py` — DI.
- `core/observability/metrics.py` — reuse `palatium_attachment_read_total` with
  `kind=reference_*` (no new metric name, 040).
- Tests: unit (policy, resolver, planner, bridge), integration (MCP path e2e with a fake repo).

**Out of scope:**

- Re-fencing prior files into the turn (see rejected alternatives).
- Changing `read_attachment` schema/pin, `ToolArgumentBuilder` behaviour for other tools.
- Frontend changes.
- `AttachmentStickinessPolicy` fence semantics (P0 contract untouched).

**Delivered after the first cut (§6a):** the ambiguity HITL card is no longer a typed
refusal — see §6a for the implementation map.

## 4. DoD

- [x] «возьми из БД и ещё раз перечитай» on a thread with exactly one attached file →
      `platform.read_attachment` is executed, worker summary is grounded in the file text.
- [x] Named file («этот файл» where the turn/prior names `СФУТ 9.03-2025.pdf`) →
      the matching attachment id is resolved deterministically.
- [x] Two files, no discernible referent → HITL card «Выберите файл» with the real
      filenames; the pick resolves deterministically and **no** arbitrary file is read.
- [x] No thread file / file row gone → honest user-facing message
      («файл недоступен в хранилище» / «в диалоге нет загруженных файлов»), never
      «вы не приложили файл» when the row exists.
- [x] `user_id` for `read_attachment` comes from the actor, never from tool args.
- [x] Unit + integration tests green; `ruff` clean; `mypy` on touched files.
- [x] Live-dev check on the screenshot thread (`ATTACHMENTS_FILE_REREAD_PCT=100`) —
      single-file thread reads back the document text; multi-file thread shows the card
      and the chosen file is read on resume (2026-10-17).
- [x] HITL ambiguity card with file names (§6a).

## 5. Enforcement

- `tests/unit/test_file_reference_policy.py` — resolution truth table (incl. ambiguity).
- `tests/unit/test_execution_planner_file_reread.py` — the axis is the only trigger;
  a fresh fence still wins; `reason_only` unchanged otherwise.
- `tests/unit/test_intent_file_reference_bridge.py` — the hint reaches the LLM payload
  and the axis survives `ContinuityPolicy` + `UserChoiceIntentPolicy`.
- `tests/unit/test_attachment_reference_resolver.py` — owner/thread scoping, ambiguous.
- `tests/unit/test_researcher_file_reread.py` — args built deterministically,
  tool invoked through the registry, cross-owner id not resolvable.
  (Lives under `tests/unit/`, not `tests/integration/`: the fake registry needs no
  live Postgres/MinIO, so the suite must run in the PR path.)
- `tests/unit/test_file_reread_rollout.py` — gate semantics: PCT=0 off, PCT=100 on,
  sticky canary bucket, dark-by-default field value.
- P0 suites (`test_p0_dialog_prior_attachment`, `test_p0_scratchpad_leak_to_attachment`,
  `test_attachment_stickiness_policy`) must stay untouched and green — the fence is not changed.

## 5a. Rollout (055)

Coverage is one key, `ATTACHMENTS_FILE_REREAD_PCT` (sticky `hash8(user_id)`, same shape as
`FORMATTER_ROLLOUT_PCT` in `core/observability/formatter_rollout.py`):

| Value | Behaviour | Stage |
|---|---|---|
| `0` | off — the turn keeps its pre-existing plan | dark default + **rollback** |
| `5` | ~5% sticky cohort | canary, then `25 → 50 → 100` |
| `100` | every caller | full cutover |

Why one key and not `ENABLED` + `PCT`: the feature is binary, so a master flag would be
redundant config — two keys only pay for themselves when the target has two values
(`FORMATTER_MODE`). `PCT=0` is the unambiguous kill switch.

Where the gate sits: `ExecutionPlanner._build_primary_step` — the single dispatch point.
`_file_reread_requested` stays pure (structure only), so the rollout decision is not
smeared into the domain predicate. `env/.env`, `.env.dev`, `.env.local.example` = `100`;
`.env.staging(.example)` = `5`; `.env.prod(.example)` / `.env.cloud.example` /
`.env.example` = `0`. Runbook: §16.11.

## 6. Open questions

- Ambiguity UX — **resolved** (§6a): card instead of refusal.
- Should the axis also cover files fetched from *knowledge* (`document_id` in
  `search_knowledge`) on a follow-up? Currently `knowledge_request` already retrieves;
  no separate axis needed until a concrete defect appears (045).

## 6a. Ambiguity HITL card (done 2026-10-17)

Deterministic identity, no LLM in the selection loop (055/070):

- `domain/hitl/file_choice.py` — `FileChoiceCardPolicy`: dedupes candidate filenames,
  caps at `MAX_FILE_CHOICE_OPTIONS`, mints `ActionSpec` ids `filesel_1..N`
  (database UUIDs never reach the client).
- `application/services/intent_hitl_flow.py` — `attach_hitl_cards(..., file_reference,
  execution_error)`: on `reference_ambiguous` mints the card titled «Выберите файл»;
  `process_hitl_choice` resolves the chosen label via
  `AttachmentReferenceResolver.resolve_explicit()` and calls
  `process_turn(attachment_ids=[...])` — no re-planning, no second LLM call.
- `attachment_reference_resolver.resolve_explicit(user_id, thread_id, filename)` —
  owner+thread scoped, newest row wins on duplicate names.
- Fail-closed: if the ask names a foreign/unknown document (`names_foreign_document`
  / `no_match`), **no** card is minted — reading another file would be worse than a refusal.
- Tests: `tests/unit/test_file_choice_card.py` (10 cases: policy, minting, resume
  without LLM, duplicate names, fail-closed). Runbook: §16.11.

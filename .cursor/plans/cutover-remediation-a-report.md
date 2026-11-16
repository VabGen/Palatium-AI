# Cutover remediation — Block A report (2026-11-16)

**STOP before B.** Agent cannot create branches / commits / PRs
(`.cursor/rules/branching.mdc`). Human opens three PRs from lists below.

## Constraint hit

| Item | Status |
|---|---|
| Agent `git checkout -b` / `commit` / `gh pr create` | **forbidden** — wait for human |
| Block B (`--strict` pin) | **not started** (A not in `dev`) |
| Blocks C–F | **not started** |

## Local verification (current WIP tree on `dev`)

| Slice | Tests | Result |
|---|---|---|
| A1 conflict-linter | `test_conflict_linter.py` + `test_conflict_linter_ci_gate.py` | **9 passed** (pre-extract); re-run after extract |
| A2 §4 | uncertainty + conductivity + assumption_mark stream + critic | **42 passed** |
| A3 §5 | `test_multi_turn_fixtures.py` | **11 passed** |
| Linter snapshot | `--fixtures --audit --judge heuristic` | hard=0, soft_raw=4, noqa=0/5 |

**soft_new (C not done):** triage set exists (`TRIAGED_SOFT_MUST_MAY`) but report still
counts raw soft only → treat soft_new as **unknown until Block C**.

**`--strict` in pin:** **no** (Block B).

## Blocker for A1 merge onto clean `origin/dev`

`AUDIT_PROMPT_REVISIONS` sha256 **DRIFT vs all 15 files on `origin/dev`**.
Pins were written against WIP CTCO prompt edits. A1 alone (linter + registry, no prompt
diffs) will either:

1. ship **wrong pins** (closures later fail), or
2. need pins **recomputed from `origin/dev`** in the A1 commit, then CTCO PR updates pins again with prompts.

**Required human step for A1:** recompute `AUDIT_PROMPT_REVISIONS` hashes from
`git show origin/dev:src/palatium_ai/<path>` *or* co-land prompt CTCO changes in a prior PR.

Also: WIP `coder.system` already **DRIFT** vs current pin (local edit after pin).

## Hygiene done in WIP (not committed)

- Extracted cutover / job pin into `tests/unit/test_conflict_linter_ci_gate.py`
  (A1-scoped; CTCO closures stay in `test_ci_prompt_controls_gates.py`).

## A1 — file list (human PR)

```
.github/workflows/conflict-linter.yml
scripts/run_conflict_linter.py
src/palatium_ai/application/agents/evals/conflict_linter/**
src/palatium_ai/application/agents/evals/prompt_revisions.py   # pins → origin/dev hashes
tests/fixtures/conflicts/**
tests/unit/test_conflict_linter.py
tests/unit/test_conflict_linter_ci_gate.py
```

Optional plan excerpt only if tracked: `.cursor/plans/prompt-audit-backlog-2026.md` §2.

**Do NOT include in A1:** prompt body CTCO edits, uncertainty, multi-turn, llm controls, web/.

Keep `continue-on-error: true`. Do **not** add `--strict`.

## A2 — file list (after A1 in `dev`)

Core (new):

```
src/palatium_ai/domain/policies/uncertainty.py
tests/fixtures/uncertainty/
tests/unit/test_uncertainty_policy.py
tests/unit/test_uncertainty_disposition_conductivity.py
tests/unit/test_formatter_assumption_mark_stream.py
```

Wiring / contracts (modified — confirm diff is §4-only before staging):

```
src/palatium_ai/domain/policies/types.py
src/palatium_ai/domain/policies/critic.py
src/palatium_ai/domain/policies/__init__.py
src/palatium_ai/domain/agents/{intent,context_packet,context_weaver,formatter,critic}.py
src/palatium_ai/application/orchestration/{nodes,node_inputs,selectors,agent_bridge}.py
src/palatium_ai/application/services/context_packet_factory.py
src/palatium_ai/application/agents/formatter/agent.py
src/palatium_ai/application/agents/critic/agent.py
src/palatium_ai/application/agents/context_enricher/weaving/{agent,parsing}.py
tests/unit/test_critic_policy.py
```

**Risk:** same files may carry CTCO / continuity / verbosity edits — human must
`git add -p` or split via worktree from clean base+A1.

## A3 — file list (after A2)

```
src/palatium_ai/application/agents/evals/multi_turn/**
tests/fixtures/multi_turn/**
tests/unit/test_multi_turn_fixtures.py
```

PR description must say: **eval on frozen stubs; agent wiring = separate PR**.
Plan status: **fixtures DONE; wiring open** (not DONE).

## Contaminants (out of A1–A3)

LLM controls / CTCO closures / web shell density / unrelated ADR docs / `scripts/ci_quality.py`
unless a dedicated prior PR.

## §4 v1.1 (D) / §5 (E) — status for final table

| Track | Status |
|---|---|
| §4 hot-path | ready for A2 PR; `out_of_scope` / `retrieval_empty` still **not wired** (D open) |
| §5 | fixtures + harness ready for A3; **wiring open** |

## Open questions (for human)

1. Recompute A1 pins from `origin/dev`, or land CTCO prompts before A1?
2. Confirm when A1–A3 are in `dev` so Block B may start.
3. Prefer worktree split vs `git add -p` for A2 entanglement?

## Next (only after A in `dev`)

Block B → pin both `continue-on-error` removal **and** `--strict`.

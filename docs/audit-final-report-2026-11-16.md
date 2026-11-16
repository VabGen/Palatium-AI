# Cutover remediation — status report (2026-11-16)

## Table

| Блок | Ветка | PR | Статус | Тесты |
|---|---|---|---|---|
| A0 CTCO prompts | `refactor/prompts-ctco-audit-2026` | merged as `687c8bc` + follow-up | **в `dev`** | 55 passed (clean) |
| A1 conflict-linter | (landed in `1eea968` mega-merge) | already on `dev` | **в `dev`** | 34 passed + recall 1.0 |
| A1.3 pin refresh | `chore/ci-refresh-audit-prompt-revisions` | **push OK; gh auth missing** | open | 34 passed |
| A2 §4 / A3 §5 | (same `1eea968`) | already on `dev` | **в `dev`** | 42 / 11 previously |
| B `--strict` pin | `fix/ci-cutover-strict-pin` | **push OK; gh auth missing** | open | **8 passed** |
| C soft_new | — | — | **ждёт merge B** | — |
| D/E/F plan+pins | `docs/cutover-plan-sync-def` | **push OK; gh auth missing** | open | uncertainty pin + multi_turn |

## Manual PR links (gh not authenticated)

- https://github.com/VabGen/Palatium-AI/pull/new/chore/ci-refresh-audit-prompt-revisions
- https://github.com/VabGen/Palatium-AI/pull/new/fix/ci-cutover-strict-pin
- https://github.com/VabGen/Palatium-AI/pull/new/docs/cutover-plan-sync-def

## Metrics (last local audit)

| Field | Value |
|---|---|
| soft_raw | **4** |
| soft_triaged | 4 known (`TRIAGED_SOFT_MUST_MAY`) — **not yet subtracted in report** |
| soft_new | **unknown until Block C** |
| noqa | 0 / 5 |
| hard | 0 |

## `--strict` in pin

| as_of | continue-on-error | `--strict` |
|---|---|---|
| 2026-12-18 | required true; live YAML | absent (live) |
| 2026-12-19 / 20 | required false; canonical post job | present |
| half-cutover (coe off, no strict) | — | **`test_cutover_requires_both_flags` fails** |

Live workflow still pre-cutover (`continue-on-error: true`, no `--strict`) — correct until 2026-12-19.

## §4 v1.1 (D)

**В плане:** `out_of_scope` / `retrieval_empty` — policy готов, hot-path wiring **open** (Intent без поля; `nodes.py` не передаёт сигналы). Не silent-done.

## §5

**fixtures + harness DONE (eval)** / **wiring open**.

## `AUDIT_PROMPT_REVISIONS`

- A0 bodies in `dev`
- A1.3 coder pin `05fb7a02…` on branch `chore/ci-refresh-audit-prompt-revisions` — **merge needed** for ALL_OK on `origin/dev`

## CI

`gh` / token unavailable → no PR URL / check-run link from agent. Open PRs via links above after `gh auth login`.

## Open questions

1. Merge A1.3 + B + D/E/F (или squash) — нужен `gh auth` или ручные PR.
2. После merge B → сигнал на **C** (`soft_new`).
3. Mega-merge `1eea968` смешал A1+A2+A3+web+LLM controls — ревью-граница размыта; отдельные PR уже не развести на истории.
4. Intent `out_of_scope` producer — нужен ли новый contract field (отдельный ADR/PR) или эвристика из task_kind?

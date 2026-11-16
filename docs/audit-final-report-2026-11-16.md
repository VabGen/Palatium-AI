# Cutover remediation — status report (2026-11-16, post-merge)

## Table

| Блок | PR / commit | Статус | Тесты |
|---|---|---|---|
| A0 CTCO prompts | `687c8bc` | **в `dev`** | 55 passed |
| A1 conflict-linter | `1eea968` | **в `dev`** | 34 passed + recall 1.0 |
| A1.3 pin refresh | #49 `4b94933` | **в `dev`** | AUDIT_PINS ALL_OK |
| A2 §4 / A3 §5 | `1eea968` | **в `dev`** | 42 / 11 |
| B `--strict` pin | #50 `7c1102d` | **в `dev`** | 8 passed |
| C soft_new | #52 `175a24c` | **в `dev`** | 16 passed |
| D/E/F plan+pins | #51 `3f19dfa` | **в `dev`** | uncertainty + multi_turn pins |

## Metrics (verified on `dev` @ `175a24c`)

| Field | Value |
|---|---|
| soft_raw | **4** |
| soft_triaged | **4** (`prompt_id` + `kind=must_may`) |
| soft_new | **0** |
| noqa | **0 / 5** |
| hard | **0** |
| AUDIT_PROMPT_REVISIONS | **ALL_OK** (15) |

## `--strict` in pin

| as_of | continue-on-error | `--strict` |
|---|---|---|
| 2026-12-18 | true (live YAML) | absent |
| 2026-12-19 / 20 | false (canonical post job) | present |
| half-cutover | — | **`test_cutover_requires_both_flags` fails** |

Live workflow remains pre-cutover until **2026-12-19**.

## §4 v1.1 (D)

**В плане:** `out_of_scope` / `retrieval_empty` — policy готов, hot-path wiring **open**
(Intent без поля; `nodes.py` не передаёт). Отдельный PR на `dev` без новой ветки —
по запросу.

## §5

**fixtures + harness DONE (eval)** / **wiring open** (Contextualizer/Intent LLM).

## Monitoring until cutover

- Watch **`soft_new`** (not `soft_raw`) on conflict-linter artifacts
- noqa ≤ 5 with headroom
- FP = new `# noqa: conflict-linter` on legitimate prompts

## Open questions

1. Intent `out_of_scope` — новый contract field или эвристика? (D wiring)
2. `retrieval_empty` re-decide — когда Researcher empty → Uncertainty? (D)
3. §5 agent wiring — отдельный трек после baseline soft_new
4. §6 lean-cut — только после 2026-12-19 + stable soft_new

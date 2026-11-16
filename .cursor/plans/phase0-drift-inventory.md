# Phase 0 — AUDIT_PROMPT_REVISIONS drift (2026-11-16)

`origin/dev` = `8da016c` (matches local HEAD).

## Hook vs branching.mdc

`deny-dangerous-shell.py` blocks force-push to protected branches / destructive ops.
**Does not** block `checkout -b` / `commit` / normal `push`. User git-override applies.

## Inventory (15/15 vs origin/dev)

| prompt_id | WIP↔pin | pin↔origin/dev | git diff vs origin | Bucket |
|---|---|---|---|---|
| analyst.system | OK | DRIFT | yes | **CTCO → A0** |
| coder.system | **DRIFT** | DRIFT | yes | **CTCO → A0** |
| text_ingestor.system | OK | DRIFT | yes | **CTCO → A0** |
| memory_keeper.system | OK | DRIFT | yes | **CTCO → A0** |
| contextualizer.system | OK | DRIFT | yes | **CTCO → A0** |
| critic.system | OK | DRIFT | yes | **CTCO → A0** |
| researcher.system | OK | DRIFT | yes | **CTCO → A0** |
| intent_classifier.system | OK | DRIFT | yes | **CTCO → A0** |
| option_synthesizer.system | OK | DRIFT | yes | **CTCO → A0** |
| attachment_map.system | OK | DRIFT | yes | **CTCO → A0** |
| image_ocr.system | OK | DRIFT | yes | **CTCO → A0** |
| pdf_vision.system | OK | DRIFT | yes | **CTCO → A0** |
| judge.system | OK | DRIFT | yes | **CTCO → A0** |
| w9_judge.system | OK | DRIFT | yes | **CTCO → A0** |
| grounding_judge.system | OK | DRIFT | yes | **CTCO → A0** |

§4/§5 keyword scan on these diffs: **no hits** (`DocumentKind` / `uncertainty` / `ASSUMPTION_MARK` / `MULTI_TURN`).

## coder.system local pin drift

- pin `0722c445…` ≠ WIP `05fb7a02…`
- Diff vs origin: CTCO rewrite (`# GOAL`/`# TASK`/`# CONTEXT`/`# EXAMPLES`/`# OUTPUT`, sandbox honesty, untrusted fence example).
- **Verdict:** CTCO, not accidental §4/§5. Goes in A0. Pin refresh = **A1.3 after A0 merge** (do not recompute now).

## Decision

Proceed **A0** with the 15 CTCO paths only. Do not touch `AUDIT_PROMPT_REVISIONS` in A0.

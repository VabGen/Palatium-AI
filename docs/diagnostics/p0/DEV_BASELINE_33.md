# uv-`dev` baseline — 2026-10-13

```
33 failed / 1686 passed / 14 skipped
(filter: not live and not llm_live and not slow)
log: CI_DEV_baseline.txt
```

Compare to poetry-`master` baseline (28 failed): same core clusters + extra formatter stream/structured-output failures on uv-`dev`.

## Groups

| Group | Count | Notes |
|---|---|---|
| env_template_parity | 13 → **0** | Fixed: missing Settings keys in `env/*.example` (+ local working copies gitignored) |
| database_resilience | 8 | Pre-existing |
| formatter_debug_stream | 3 | uv-dev delta vs master |
| structured_output (formatter) | 3 | uv-dev delta vs master |
| attachment_turn_injection | 2 | formatter `fast_path` |
| memory HITL e2e | 2 | Pre-existing |
| formatter_action_contract | 1 | Pre-existing |
| frontend_widget_delivery | 1 | Pre-existing |

## Remaining after env fix (~20)

Not scoped as xfail yet — track as tech debt; do not deselect silently without issue link.

## P0 suite

`scripts/smoke_p0_attachment.py` → **32 passed** (orthogonal to baseline red).

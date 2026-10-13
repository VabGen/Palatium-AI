## P0-A: Attachment fence substitution via cross-thread rehydrate

### Root cause
`AttachmentRepository.get_many(ids, user_id)` не фильтрует по `thread_id`.
Rehydrate из dialog prior резолвит UUID attachment из чужого треда того же
пользователя и фенсит его в `untrusted_context` текущего turn.

Диагностика: docs/diagnostics/p0/
- A.1 dataflow: attachment_refs derived from fence, не SoT
- A.2a: failing unit test — get_many без thread_id
- A.2b: clean-prior integration PASS
- A.2e H5b ×2: polluted-prior integration FAIL → fence = contract.pdf (before fix)

### Fix
- `get_many(*, thread_id)` — обязательный kwarg
- SQL: `WHERE id IN (...) AND user_id = $1 AND thread_id = $2`
- Caller: `build_turn_context` пробрасывает `thread_id`; rehydrate soft-skips missing/cross-thread ids (entry explicit upload still raises `AttachmentNotFoundError`)

### Non-goals
- Dialog write path (H5a: PASS, не требуется)
- Contextualizer / memory recall — закрыто в P0-B (kind-gate на `dev`)
- Источник pollution dialog prior (non-blocker, фикс блокирует усилитель)
- A.2d — восстановлен и зелёный после P0-B

### Evidence
- Before: A.2a FAIL, A.2e H5b FAIL
- After: A.2a PASS, A.2e H5b PASS, A.2b PASS (no regression)

```bash
uv run python -m pytest tests/unit/test_p0_get_many_thread_isolation.py tests/integration/test_p0_dialog_prior_attachment.py tests/integration/test_p0_attachment_turn_isolation.py -q
# 5 passed
```

### Phase 5 unblock
Closes P0-A. P0-B (recall scope) остаётся открытым, не блокирует Phase 5.

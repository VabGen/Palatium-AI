# memory-os-write — reference

## Allowed write paths

1. MCP `save_memory` / `forget_memory` / `extract_transcript_memories` (070).
2. `MemoryWriteService.put_system` for ContextBuilder compact preserve (060/065).
3. Sleep-time extract worker → medium via MemoryKeeper (not promote).

## Forbidden

- Agent → `MemoryPort.put` / raw SQL.
- Writing `.agent/MEMORY.md` as product SoT (DX Cursor only).
- Silent PII into long-term without `contains_pii=true`.
- Promote from extract worker (extract ⊥ promote).

## Checks before merge

- Secret scanner on text.
- PII classify flag persisted.
- Audit event on mutation (040).

---
name: memory-os-write
description: >-
  When saving or compacting durable memory: use gated MemoryWriteService / MCP
  save_memory only (secret scan + PII + audit). Never direct MemoryPort.put from
  agents. Use when implementing Write/Compress paths or reviewing memory mutations.
---

# Memory OS — Write

Product memory Write is gated. Prefer MCP `save_memory` / extract enqueue; compact
persist goes through `MemoryWriteService.put_system`.

Call `skill_reference(name="memory-os-write")` for the checklist and anti-patterns.

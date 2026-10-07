---
name: memory-os-write
version: 1.0.0
description: >-
  Use when implementing or reviewing durable memory Write/Compress paths:
  gated MemoryWriteService / MCP save_memory only (secret scan + PII + audit).
  Never call MemoryPort.put directly from agents.
---

# Memory OS — Write

Product memory Write is gated. Prefer MCP `save_memory` / extract enqueue; compact
persist goes through `MemoryWriteService.put_system`.

Call `skill_reference(name="memory-os-write")` for the checklist and anti-patterns.

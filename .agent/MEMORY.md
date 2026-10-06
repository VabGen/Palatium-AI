# Agent memory (Cursor DX only)

**Not product SoT.** Palatium runtime must never load this file into agent
prompts or `memory.entries`. Durable product memory is hybrid cortex (060):
Postgres medium + Neo4j promote + dual TTL checkpointer.

Use this file for **local Cursor session notes** (preferences, WIP pointers).
Do not treat edits here as user-facing memory mutations — those go through MCP
`save_memory` / extract / promote.

Procedural product skills live under `skills/procedural/` and load via
progressive disclosure (`skill_catalog` + MCP `skill_reference`).

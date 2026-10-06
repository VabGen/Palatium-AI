# hitl-irreversible — reference

## Always HITL (020)

- Email / messaging send
- DB / filesystem / EDMS writes (incl. attribute moves)
- Neo4j MERGE/SET/DELETE
- External write HTTP
- Finance, PII access, arbitrary code exec
- `confidence < confidence_threshold`

## Card rules

- Clickable actions, unique `card_id`, TTL by irreversibility class.
- First response wins; Redis is SoT for card state.
- LangGraph: `interrupt()` + `Command(resume=...)`, not `interrupt_before`.

## Not HITL

- Read tools: search, get, list, `graph_query`, `skill_reference`.

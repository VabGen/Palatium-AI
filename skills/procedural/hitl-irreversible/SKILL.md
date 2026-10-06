---
name: hitl-irreversible
description: >-
  When planning irreversible actions (EDMS write, graph mutate, PII access,
  code exec, finance): require HITL interrupt()+card before the step. Use when
  adding tools, routes, or reviewing write paths for Zero Trust (020).
---

# HITL for irreversible work

Read-only tools skip HITL. Writes and high-risk classes need a one-shot card.

Call `skill_reference(name="hitl-irreversible")` for the class list and card rules.

---
name: hitl-irreversible
version: 1.0.0
description: >-
  Use when adding tools, routes, or reviewing write paths that may perform
  irreversible actions (EDMS write, graph mutate, PII access, code exec,
  finance): require HITL interrupt()+one-shot card before the step (020).
---

# HITL for irreversible work

Read-only tools skip HITL. Writes and high-risk classes need a one-shot card.

Call `skill_reference(name="hitl-irreversible")` for the class list and card rules.

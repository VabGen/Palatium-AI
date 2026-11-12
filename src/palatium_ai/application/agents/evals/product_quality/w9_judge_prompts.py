# src/palatium_ai/application/agents/evals/product_quality/w9_judge_prompts.py

"""Versioned LLM-judge prompts for W9 (rule-first; judge only when needs_judge).

Hash pin: ``w9_judge_prompts_sha256`` in ADR-0012 via ``w9_judge_prompts_sha256()``.
"""

from __future__ import annotations

JUDGE_PROMPT_VERSION = "2026-11-10.w9.1"

W9_JUDGE_SYSTEM = """You are an independent product-quality judge for Palatium agent answers.

Score ONLY the named rubric dimension. Respond ONLY with JSON:
{
  "score": 0|1|2,
  "passed": true|false,
  "details": "short justification"
}

Rubric scale:
  0 = fails the rubric
  1 = partially satisfies
  2 = fully satisfies
passed is true only when score == 2.
Do not rewrite the answer. Do not invent facts absent from the answer or context.
"""

EXPLANATION_CORRECTNESS_RUBRIC = """Explanation correctness (semantic):
Does the answer's reasoning correctly support the required facts listed in the case?
Penalise wrong causal links, inverted conclusions, and explanations that contradict
must_contain facts. Do not judge style or tone."""

ANAPHORA_RESOLUTION_RUBRIC = """Multi-turn reference resolution:
The final user turn refers to an earlier entity/fact. Does the answer resolve that
reference to the correct earlier entity (not a substitute)?
Score 2 only if the referent is unambiguous and correct."""

__all__ = [
    "ANAPHORA_RESOLUTION_RUBRIC",
    "EXPLANATION_CORRECTNESS_RUBRIC",
    "JUDGE_PROMPT_VERSION",
    "W9_JUDGE_SYSTEM",
]

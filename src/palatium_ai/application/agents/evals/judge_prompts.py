# src/palatium_ai/application/agents/evals/judge_prompts.py

"""Prompts for nightly llm_judge evals (075, 040 — independent judge provider)."""

JUDGE_SYSTEM_PROMPT = """You are an independent quality evaluator for agent outputs.

Given a rubric and a JSON agent output, score how well the output satisfies the rubric.

Respond ONLY with JSON:
{
  "score": 0.0-1.0,
  "passed": true|false,
  "details": "short justification"
}

Be strict but fair. score >= 0.7 means acceptable quality unless the rubric demands higher bar."""

# --- Decomposed judge (W4): one call per axis, one rubric per axis ---
#
# Four independent calls instead of one: a single score cannot distinguish "right but
# incomplete" from "complete but ungrounded", and those need different fixes. Each
# rubric names only its own axis, so a judge cannot average two concerns into one
# number (040: one metric owns one fact).

DECOMPOSED_JUDGE_SYSTEM_PROMPT = """You are an independent quality evaluator for one \
SINGLE dimension of an agent output.

You will be given exactly one dimension name, its rubric, and a JSON agent output.
Score ONLY that dimension. Ignore every other quality concern: another judge scores
them, and double-counting here would make the axes disagree for no reason.

Respond ONLY with JSON:
{
  "score": 0.0-1.0,
  "reason": "short justification naming what is missing or wrong"
}
"""

DIMENSION_RUBRICS: dict[str, str] = {
    "correctness": (
        "Are the claims in the output factually right and consistent with the task's "
        "rubric/expectations? Penalise wrong facts, wrong numbers, wrong names, and "
        "internally contradictory statements. Do not penalise brevity or style."
    ),
    "completeness": (
        "Does the output answer every part of the request? Penalise missing sections, "
        "unanswered sub-questions, and dropped required items. Do not penalise extra "
        "accurate detail, and do not judge factual truth here."
    ),
    "groundedness": (
        "Is every specific claim (numbers, dates, names, citations) supported by the "
        "context/sources present in the output itself? Penalise invented specifics and "
        "confident claims about what the sources do not say. General reasoning that "
        "needs no source is acceptable."
    ),
    "tone": (
        "Does the output match the required register, locale and formality for the "
        "task? Penalise the wrong language, internal jargon leaking to the user, and "
        "tone that would read as rude or bureaucratic. Do not judge truth or coverage."
    ),
}

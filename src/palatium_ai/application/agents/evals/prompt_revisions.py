# src/palatium_ai/application/agents/evals/prompt_revisions.py

"""Pinned revisions for prompts touched by the 2026-11 CTCO / liveliness audit.

Runtime logging still uses ``prompt_file_version`` (sha16) via Harness (W8.7).
This registry is the audit SoT: ``prompt_id`` + full sha256 + change date + ADR/eval
pointer. Changing a listed file without updating the pin fails CI.
"""

from __future__ import annotations

import hashlib

from pathlib import Path

from pydantic import BaseModel, Field

_REPO_ROOT = Path(__file__).resolve().parents[5]
_SRC = _REPO_ROOT / "src" / "palatium_ai"


class PromptRevision(BaseModel, frozen=True):
    """One audited prompt artifact."""

    prompt_id: str = Field(min_length=1)
    relative_path: str = Field(min_length=1)
    sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    changed_on: str = Field(pattern=r"^\d{4}-\d{2}-\d{2}$")
    adr_or_eval: str = Field(min_length=1)


#: Update pin + [constitution-update] when Critic changes (ADR-0010).
#: Update ADR-0012 when w9_judge changes.
AUDIT_PROMPT_REVISIONS: tuple[PromptRevision, ...] = (
    PromptRevision(
        prompt_id="analyst.system",
        relative_path="application/agents/analyst/prompts.py",
        sha256="1f1208b403eb7505c961b677802368ddfcc2b82734a995c0a3480d319eec4837",
        changed_on="2026-11-16",
        adr_or_eval="golden_manifest:analyst + tests/unit/test_prompt_audit_closures.py",
    ),
    PromptRevision(
        prompt_id="coder.system",
        relative_path="application/agents/coder/prompts.py",
        sha256="05fb7a02fc5fefcd7ec081697e5db7d55996625a3e84c5e811af6446a5d5c60f",
        changed_on="2026-11-16",
        adr_or_eval="golden_manifest:coder + tests/unit/test_prompt_audit_closures.py",
    ),
    PromptRevision(
        prompt_id="text_ingestor.system",
        relative_path="application/agents/text_ingestor/prompts.py",
        sha256="1e9d6857ce6932e616fdbe7efba6aeeff31e60941f4a73afc453224ab0c2f91e",
        changed_on="2026-11-16",
        adr_or_eval="golden_manifest:text_ingestor + tests/unit/test_prompt_audit_closures.py",
    ),
    PromptRevision(
        prompt_id="memory_keeper.system",
        relative_path="application/agents/memory_keeper/prompts.py",
        sha256="6c3623a5e79dbc81ec085b7313516818a359c870214fd3b28f79a50143675fca",
        changed_on="2026-11-17",
        adr_or_eval="golden_manifest:memory_keeper + tests/unit/test_memory_keeper_prompt.py",
    ),
    PromptRevision(
        prompt_id="contextualizer.system",
        relative_path="application/agents/context_enricher/continuation/prompts.py",
        sha256="0aaaf48e6c1491ee564ee1b168ac60534538de020aa4979c829f83be1738cbc9",
        changed_on="2026-11-16",
        adr_or_eval="golden_manifest:context_enricher + tests/unit/test_prompt_audit_closures.py",
    ),
    PromptRevision(
        prompt_id="critic.system",
        relative_path="application/agents/critic/prompts.py",
        sha256="78e8fdf508371a35e0f533aed58a6f73f360f59179ec7728e9bbed1d811c9dc4",
        changed_on="2026-11-16",
        adr_or_eval="ADR-0010 verify_prompts_sha256 + tests/eval/test_w78_observability_contracts.py",
    ),
    PromptRevision(
        prompt_id="researcher.system",
        relative_path="application/agents/researcher/prompts.py",
        sha256="e94904ef7f18e8d501b7e0df78e6c7a1f48c387153c9be6c9836ab7c0ba06bc0",
        changed_on="2026-11-17",
        adr_or_eval="golden_manifest:researcher + tests/unit/test_document_synthesis_policy.py",
    ),
    PromptRevision(
        prompt_id="intent_classifier.system",
        relative_path="application/agents/intent_classifier/prompts.py",
        sha256="696eb730e0c0830ce81ad90b1c86fc4d29c15db848816db665647a53b69ad9b4",
        changed_on="2026-11-17",
        adr_or_eval="golden_manifest:intent_classifier + tests/unit/test_intent_file_reference_bridge.py",
    ),
    PromptRevision(
        prompt_id="option_synthesizer.system",
        relative_path="application/services/option_synthesizer.py",
        sha256="b12133902790184e7e727317eef81abb1366417b6b1d1283489826da4f860d35",
        changed_on="2026-11-16",
        adr_or_eval="tests/unit/test_prompt_audit_closures.py",
    ),
    PromptRevision(
        prompt_id="attachment_map.system",
        relative_path="application/wiring.py",
        sha256="85089f07e7dbbd4bd15c57b8c5af87c8cc5b3a1298a8fab7cc3e58e85b62881c",
        changed_on="2026-11-16",
        adr_or_eval="tests/unit/test_prompt_audit_closures.py",
    ),
    PromptRevision(
        prompt_id="image_ocr.system",
        relative_path="infrastructure/parsing/image_ocr.py",
        sha256="b675e0854e15745cda89c21318c6283e67565c076036938fe61f501f05c9ddbe",
        changed_on="2026-11-16",
        adr_or_eval="tests/unit/test_prompt_audit_closures.py",
    ),
    PromptRevision(
        prompt_id="pdf_vision.system",
        relative_path="infrastructure/parsing/pdf_vision.py",
        sha256="60b86a251fb3fac24de5b05522a3b41ae9eec33384fd7e62d6d1c4763afaf480",
        changed_on="2026-11-16",
        adr_or_eval="tests/unit/test_prompt_audit_closures.py",
    ),
    PromptRevision(
        prompt_id="judge.system",
        relative_path="application/agents/evals/judge_prompts.py",
        sha256="f769db3359557b16872a7fdee2920e9c49a20742af42f0eb00994c37fd3d248f",
        changed_on="2026-11-16",
        adr_or_eval="tests/unit/test_prompt_audit_closures.py",
    ),
    PromptRevision(
        prompt_id="w9_judge.system",
        relative_path="application/agents/evals/product_quality/w9_judge_prompts.py",
        sha256="a7c1a50a4938fdea7e164fed30ab18811bedb0140fdcc43c8c6e1af2cac3f2c1",
        changed_on="2026-11-16",
        adr_or_eval="ADR-0012 w9_judge_prompts_sha256",
    ),
    PromptRevision(
        prompt_id="grounding_judge.system",
        relative_path="core/observability/grounding_guardrail.py",
        sha256="06ce8e1f5c27ef8a130a18da67847003b350cfcecf17af08c886603a92dc066e",
        changed_on="2026-11-16",
        adr_or_eval="tests/unit/test_prompt_audit_closures.py",
    ),
)


def file_sha256(relative_path: str) -> str:
    """sha256 of ``src/palatium_ai/<relative_path>``."""
    return hashlib.sha256((_SRC / relative_path).read_bytes()).hexdigest()


__all__ = ["AUDIT_PROMPT_REVISIONS", "PromptRevision", "file_sha256"]

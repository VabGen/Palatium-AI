# src/palatium_ai/application/services/pii_gate.py

"""Write-time PII gate: classify once, report once (020, 040).

Every durable write path (system put, HITL ``save_memory``, fact persistence) needs the
same answer *and* the same observability signal. Keeping both in one function is what
stops a new write path from silently skipping the metric — or the scan.
"""

from __future__ import annotations

from palatium_ai.core.observability.metrics import agent_metrics
from palatium_ai.domain.memory.pii import classify_pii


def classify_for_write(*, text: str, client_flag: bool = False) -> bool:
    """Return ``contains_pii`` for a storage write, counting detected classes."""
    classification = classify_pii(text=text, client_flag=client_flag)
    if classification.kinds:
        agent_metrics.record_pii_detected(kinds=classification.kinds, profile="strict")
    return classification.contains


__all__ = ["classify_for_write"]

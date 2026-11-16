# src/palatium_ai/domain/policies/revision.py

"""Whether a turn produces a *revision* of the prior answer (W7b, 055).

``revision_of`` is about document identity, not about feedback: a document is a revision
when this turn reworks the previous answer instead of answering a fresh ask. Two signals
say exactly that, and neither needs a model opinion:

* ``revision_feedback`` — the previous answer was rejected (critic loop or user review)
  and this turn re-answers it;
* ``transformation`` ≠ ``none`` — restructure / expand / shorten / rewrite all take the
  prior answer as their source, so the result continues its lineage.

A follow-up question that merely *references* the prior answer (its content is used as
evidence) is a new document — pairing it with the previous one would show a diff nobody
asked for.
"""

from __future__ import annotations

from palatium_ai.domain.policies.transform import TransformPolicy
from palatium_ai.domain.policies.types import TRANSFORMATION_DEFAULT, TransformationKind


class RevisionPolicy:
    """Pure domain policy: does this turn revise the previous document?"""

    @classmethod
    def continues_prior_document(
        cls,
        *,
        revision_feedback: str | None,
        transformation: TransformationKind | str | None = TRANSFORMATION_DEFAULT,
    ) -> bool:
        if (revision_feedback or "").strip():
            return True
        return TransformPolicy.coerce(transformation) != "none"

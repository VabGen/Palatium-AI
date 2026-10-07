# src/palatium_ai/domain/memory/bayesian_trust.py

"""Beta-Bernoulli trust for long-term facts (Wave M8, eval-gated).

Maps evidence counts to a confidence in [0, 1]. Opt-in via
``MEMORY_BAYESIAN_TRUST`` — default promote path keeps scalar confidence.
"""

from __future__ import annotations

from pydantic import BaseModel, Field


class BetaTrust(BaseModel):
    """Conjugate Beta prior for binary evidence (success / failure)."""

    model_config = {"frozen": True}

    alpha: float = Field(default=1.0, gt=0.0, le=1_000_000.0)
    beta: float = Field(default=1.0, gt=0.0, le=1_000_000.0)

    def mean(self) -> float:
        """Posterior mean = alpha / (alpha + beta)."""
        return self.alpha / (self.alpha + self.beta)

    def observe_success(self, *, weight: float = 1.0) -> BetaTrust:
        """Evidence that the fact remains true / was reinforced."""
        w = max(0.0, float(weight))
        return BetaTrust(alpha=self.alpha + w, beta=self.beta)

    def observe_failure(self, *, weight: float = 1.0) -> BetaTrust:
        """Evidence that the fact was contradicted / superseded."""
        w = max(0.0, float(weight))
        return BetaTrust(alpha=self.alpha, beta=self.beta + w)

    @classmethod
    def from_confidence(cls, confidence: float, *, strength: float = 2.0) -> BetaTrust:
        """Seed a prior whose mean ≈ confidence with pseudo-count ``strength``."""
        c = max(0.0, min(1.0, float(confidence)))
        s = max(0.1, float(strength))
        return cls(alpha=max(1e-6, c * s), beta=max(1e-6, (1.0 - c) * s))

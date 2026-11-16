# src/palatium_ai/domain/content/citations/models.py

"""Provider-neutral citation anchor (W3a).

Providers do not mean the same thing by "position", and conflating them is the bug
this model exists to prevent:

* OpenAI ``url_citation`` annotations carry ``start_index``/``end_index`` — positions
  in the **answer** the model just wrote, not in the source. They belong in
  ``answer_range``.
* Anthropic document citations carry ``start_char_index``/``end_char_index`` or
  ``start_page_number`` — positions in the **source document**. They belong in
  ``source_range``/``page``.
* A URL-only citation has no positions at all: ``anchor="url_only"`` and both ranges
  stay ``None``. ``None`` means "the provider did not say", never "zero".

Forcing all three into one ``(start, end)`` pair would either silently mislabel an
answer offset as a source offset, or invent ``0`` for an unknown location. Both are
worse than an honest ``None``.
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field, model_validator

CitationAnchor = Literal["char_location", "page_location", "content_block_location", "url_only"]


class CitationRef(BaseModel):
    """One citation the provider attached to its answer.

    ``quote`` is the provider's text verbatim — it is never rewritten for display;
    ``domain/content/citations/normalizer.py`` normalises whitespace only when it
    compares the quote with the answer.
    """

    model_config = {"frozen": True}

    #: User-facing source label (filename or URL). Never an internal attachment id.
    source_ref: str = Field(min_length=1, max_length=512)
    #: Attachment id this label resolves to, filled by the server **only** when the
    #: turn's fence headers map the label to exactly one upload. It is not emitted by
    #: the model (``citations`` is outside the strict schema) and not derivable on the
    #: client: matching by basename would open another user's same-named file (020).
    source_id: str | None = Field(default=None, max_length=36)
    quote: str | None = None
    #: 1-based page in the source, when the provider reports pages.
    page: int | None = Field(default=None, ge=1)
    #: ``(start, end)`` inside the SOURCE document.
    source_range: tuple[int, int] | None = None
    #: ``(start, end)`` inside the ANSWER text the provider returned.
    answer_range: tuple[int, int] | None = None
    anchor: CitationAnchor = "url_only"

    @model_validator(mode="after")
    def _check_anchor(self) -> CitationRef:
        for name in ("source_range", "answer_range"):
            span = getattr(self, name)
            if span is not None and (span[0] < 0 or span[1] <= span[0]):
                raise ValueError(f"{name} must be a non-empty (start, end) with 0 <= start < end")
        if self.anchor == "url_only" and (self.source_range is not None or self.page is not None):
            raise ValueError("url_only citation cannot carry source positions")
        if self.anchor != "url_only" and self.quote is None and self.source_range is None and self.page is None:
            raise ValueError(f"{self.anchor} citation needs a quote, a source_range or a page")
        return self


__all__ = ["CitationAnchor", "CitationRef"]

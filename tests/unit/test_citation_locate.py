# tests/unit/test_citation_locate.py

"""Source-citation locator: quote-first, offset-second (W3b-2).

The locator must never point at a plausible-looking place. Every failure case here
exists because the naive alternative (`trust the offset`, `take the first match`)
silently highlights the wrong text — worse than showing nothing (055).
"""

from __future__ import annotations

import pytest

from palatium_ai.core.types.citations import CITATION_WINDOW_CHARS
from palatium_ai.domain.content.citations import CitationLocator, citation_window
from palatium_ai.domain.content.citations.locate import CitationLocation

_QUOTE = "Оплата в течение 5 рабочих дней"
_TEXT = f"Договор поставки.\n\n1. Предмет. Поставщик передаёт товар.\n\n2. Расчёт.   {_QUOTE} с момента подписания.\n\n3. Прочее."


def _locate(
    *,
    text: str = _TEXT,
    quote: str | None = _QUOTE,
    declared_range: tuple[int, int] | None = None,
    anchor: str = "char_location",
) -> CitationLocation:
    return CitationLocator.locate(
        text=text,
        quote=quote,
        declared_range=declared_range,
        anchor=anchor,  # type: ignore[arg-type]
    )


def test_quote_is_located_when_the_provider_gives_no_offset() -> None:
    location = _locate()

    assert location.outcome == "quote_match"
    assert location.highlighted
    assert location.start is not None
    assert location.end is not None
    assert _TEXT[location.start : location.end] == _QUOTE


def test_verified_declared_range_wins_over_the_search() -> None:
    start = _TEXT.index(_QUOTE)
    location = _locate(declared_range=(start, start + len(_QUOTE)))

    assert location.outcome == "declared_range"
    assert (location.start, location.end) == (start, start + len(_QUOTE))


def test_declared_range_is_a_hint_when_the_quote_contradicts_it() -> None:
    """A provider offset shifted by our fence prefix must not win over the evidence."""
    wrong = (_TEXT.index("1. Предмет"), _TEXT.index("1. Предмет") + len(_QUOTE))
    location = _locate(declared_range=wrong)

    assert location.outcome == "quote_match"
    assert location.start is not None
    assert _TEXT[location.start : location.start + len(_QUOTE)] == _QUOTE


def test_wider_declared_range_around_the_quote_still_agrees() -> None:
    """Some providers report the paragraph, not the quote — that is still trustworthy."""
    start = _TEXT.index(f"2. Расчёт.   {_QUOTE} с момента")
    end = start + len(f"2. Расчёт.   {_QUOTE} с момента")
    location = _locate(declared_range=(start, end))

    assert location.outcome == "declared_range"
    assert (location.start, location.end) == (start, end)


def test_content_block_location_never_highlights_by_offset() -> None:
    """Block indexes stored in ``source_range`` are not character offsets (W3a)."""
    location = _locate(declared_range=(0, 3), anchor="content_block_location")

    assert location.outcome == "quote_match"
    assert location.start is not None
    assert _TEXT[location.start : location.start + len(_QUOTE)] == _QUOTE


def test_two_occurrences_are_ambiguous_not_the_first_one() -> None:
    doubled = f"{_TEXT}\n\nПовтор: {_QUOTE}."

    location = _locate(text=doubled)

    assert location.outcome == "ambiguous_quote"
    assert not location.highlighted


def test_quote_absent_from_the_source_is_not_found() -> None:
    location = _locate(quote="Такого текста в договоре нет")

    assert location.outcome == "quote_not_found"
    assert (location.start, location.end) == (None, None)


def test_whitespace_differences_do_not_break_the_match() -> None:
    """Providers reflow text; the comparison collapses whitespace, the source does not."""
    location = _locate(quote="Оплата  в течение\n5 рабочих дней")

    assert location.outcome == "quote_match"
    assert location.start is not None
    assert _TEXT[location.start : location.start + len(_QUOTE)] == _QUOTE


def test_offsets_are_absolute_even_after_leading_whitespace_is_trimmed() -> None:
    text = f"\n\n   {_QUOTE} далее"
    location = _locate(text=text)

    assert location.outcome == "quote_match"
    assert location.start is not None
    assert text[location.start : location.end or 0].startswith("Оплата")


def test_empty_source_is_reported_as_no_text() -> None:
    assert _locate(text="   \n  ").outcome == "no_text"


def test_empty_quote_cannot_locate_anything() -> None:
    assert _locate(quote="").outcome == "quote_not_found"


@pytest.mark.parametrize(
    "text,focus",
    (
        ("короткий текст", None),
        ("короткий текст", (0, 7)),
    ),
)
def test_short_source_is_returned_whole(text: str, focus: tuple[int, int] | None) -> None:
    window = citation_window(text, focus=focus)

    assert (window.start, window.end) == (0, len(text))
    assert window.text == text


def test_window_keeps_the_highlight_inside_and_stays_bounded() -> None:
    text = "а" * 5000 + _QUOTE + "б" * 5000
    focus = (5000, 5000 + len(_QUOTE))

    window = citation_window(text, focus=focus)

    assert window.end - window.start <= CITATION_WINDOW_CHARS
    assert window.start <= focus[0]
    assert window.end >= focus[1]
    assert text[window.start : window.end] == window.text


def test_window_without_focus_shows_the_head() -> None:
    text = "а" * 5000

    window = citation_window(text, focus=None)

    assert (window.start, window.end) == (0, CITATION_WINDOW_CHARS)


def test_oversized_span_still_yields_a_bounded_window_at_the_span_start() -> None:
    """Defence in depth: the request cap makes this unreachable, but a window is never unbounded."""
    text = "а" * 100 + "ь" * (CITATION_WINDOW_CHARS + 500) + "б" * 100
    focus = (100, 100 + CITATION_WINDOW_CHARS + 500)

    window = citation_window(text, focus=focus)

    assert window.start == focus[0]
    assert window.end - window.start == CITATION_WINDOW_CHARS

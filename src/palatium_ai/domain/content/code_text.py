# src/palatium_ai/domain/content/code_text.py

"""Fenced-code text kept verbatim: repair a provider's HTML-entity slip (055).

The schema-first contract asks the provider for a ``ContentDocument`` JSON, and
``CodeBlock.content`` is user-facing source code. Some providers HTML-escape the
quotes inside that string (``{"name": "Alice"}`` → ``{&quot;name&quot;: …}``)
because they treat the surrounding JSON/XML-ish payload as markup. The client
renders code through a text node, so the entities reach the user literally —
double-escaped in the DOM (E2E-05).

This is a contract repair, not a phrase list: a code snippet is text, never HTML,
so an entity-escaped fragment is unescaped exactly once at the typed-block
boundary. Detection is structural — a snippet qualifies only when it carries
quote entities **and** no raw double quote, which is the signature of a fully
escaped fragment. Code that legitimately shows ``&quot;`` also contains the raw
quotes of the string it sits in (``print("&quot;")``), so it is left untouched.

Markup entities (``&lt;``/``&gt;``) are deliberately out of scope: an HTML snippet
legitimately contains them, so unescaping would corrupt correct code.
"""

from __future__ import annotations

import html
import re

#: Quote entities only: a fragment escaped by a provider escapes *every* quote,
#: and quotes are what breaks the JSON payload it was written inside. The optional
#: ``amp;`` prefix covers a provider that escaped an already-escaped fragment.
_QUOTE_ENTITIES = re.compile(
    r"&(?:amp;)?(?:quot|apos|#0*34|#x0*22|#0*39|#x0*27);",
    re.IGNORECASE,
)
#: Any entity reference, used to decide whether a second round remains.
_ANY_ENTITY = re.compile(r"&(?:[a-zA-Z][a-zA-Z0-9]{1,31}|#\d{1,7}|#x[0-9a-fA-F]{1,6});")
#: Bounded: a provider may escape twice, but never intentionally three times.
_MAX_UNESCAPE_ROUNDS = 2


def normalize_code_entities(content: str) -> str:
    """Undo provider HTML escaping in a code snippet; leave real entities alone."""
    result = content
    for _ in range(_MAX_UNESCAPE_ROUNDS):
        if '"' in result or not _QUOTE_ENTITIES.search(result):
            break
        decoded = html.unescape(result)
        if decoded == result:
            break
        result = decoded
        if not _ANY_ENTITY.search(result):
            break
    return result


__all__ = ["normalize_code_entities"]

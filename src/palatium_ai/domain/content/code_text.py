# src/palatium_ai/domain/content/code_text.py

r"""Fenced-code text kept verbatim: repair provider slips that hurt readability (055).

The schema-first contract asks the provider for a ``ContentDocument`` JSON, and
``CodeBlock.content`` is user-facing source code. Two failure modes reach the
client as an unreadable one-liner:

1. HTML-escaped quotes (``{"name": "Alice"}`` → ``{&quot;name&quot;: …}``) —
   the client renders a text node, so entities show literally (E2E-05).
2. Collapsed newlines — the model minifies the snippet or double-escapes
   ``\n`` inside the JSON string, so a multi-statement program scrolls
   horizontally as a single line.

Repairs are structural (language + shape of the string), never phrase lists.
Markup entities (``&lt;``/``&gt;``) stay out of scope: an HTML snippet may
legitimately contain them.
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

#: Literal backslash-n / backslash-t that survived double JSON escaping.
_LITERAL_ESCAPES = re.compile(r"\\([ntr])")
_ESCAPE_MAP = {"n": "\n", "t": "\t", "r": "\r"}

#: Languages where ``><`` soft-breaks are safe (markup, not comparison operators).
_MARKUP_LANGS = frozenset(
    {
        "html",
        "htm",
        "xml",
        "svg",
        "xhtml",
        "vue",
        "jsx",
        "tsx",
        "svelte",
    }
)

#: ``def foo(...) -> T: body`` jammed on one line (annotation colons allowed).
_PY_DEF_BODY = re.compile(
    r"(?P<header>(?:async\s+)?def\b.+?\))\s*(?P<ret>->\s*[^:]+)?\s*:"
    r"[ \t]+(?P<body>\S)",
)
#: ``class Foo(Bar): body`` without nested type colons in the header.
_PY_CLASS_BODY = re.compile(
    r"(?P<header>class\b[^:\n]+):[ \t]+(?P<body>\S)",
)

#: Minified statement glue — only when the whole snippet is still one line.
_STMT_SEMI = re.compile(r";[ \t]+")


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


def _expand_literal_escapes(content: str) -> str:
    r"""Turn leftover ``\n`` / ``\t`` into real control chars when no newline exists.

    Double-encoded JSON (``\\n`` → string ``\n``) is a common provider slip;
    expanding only when the snippet has zero real newlines keeps authored
    ``print("\n")`` demos intact — those still contain a real newline elsewhere
    or are short enough that a single-line demo is intentional.
    """
    if "\n" in content or not _LITERAL_ESCAPES.search(content):
        return content
    return _LITERAL_ESCAPES.sub(lambda m: _ESCAPE_MAP[m.group(1)], content)


def _soft_break_markup(content: str) -> str:
    """Insert a newline between adjacent tags in a minified HTML/XML blob."""
    if "\n" in content or "<" not in content:
        return content
    # ``><`` → ``>\n<``; keep attribute spaces inside a tag untouched.
    return re.sub(r">\s*<", ">\n<", content)


def _soft_break_python(content: str) -> str:
    """Split a one-line ``def``/``class`` header from its body when jammed together."""
    if "\n" in content or len(content) < 60:
        return content
    def_match = _PY_DEF_BODY.search(content)
    if def_match is not None:
        ret = def_match.group("ret")
        header = def_match.group("header") + (f" {ret.strip()}" if ret else "") + ":"
        return content[: def_match.start()] + f"{header}\n    {def_match.group('body')}" + content[def_match.end() :]
    class_match = _PY_CLASS_BODY.search(content)
    if class_match is None:
        return content
    return (
        content[: class_match.start()]
        + f"{class_match.group('header')}:\n    {class_match.group('body')}"
        + content[class_match.end() :]
    )


def _soft_break_statements(content: str) -> str:
    """Split ``a; b; c`` one-liners — never touch strings with real newlines."""
    if "\n" in content or ";" not in content or len(content) < 60:
        return content
    # Skip if it looks like a for-loop header or only one semicolon in a short expr.
    if content.count(";") < 1:
        return content
    return _STMT_SEMI.sub(";\n", content)


def normalize_code_content(content: str, *, language: str = "text") -> str:
    """Entity repair + restore readable line structure for collapsed snippets."""
    result = normalize_code_entities(content)
    result = _expand_literal_escapes(result)
    lang = (language or "text").strip().lower()
    if lang in _MARKUP_LANGS or (lang == "text" and result.lstrip().startswith("<!")):
        result = _soft_break_markup(result)
    if lang in {"python", "py", "python3"}:
        result = _soft_break_python(result)
    if lang in {"javascript", "js", "typescript", "ts", "java", "c", "cpp", "go", "rust"}:
        result = _soft_break_statements(result)
    return result


__all__ = ["normalize_code_content", "normalize_code_entities"]

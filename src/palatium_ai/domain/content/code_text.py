# src/palatium_ai/domain/content/code_text.py

r"""Fenced-code text kept verbatim: repair provider slips that hurt readability (055).

The schema-first contract asks the provider for a ``ContentDocument`` JSON, and
``CodeBlock.content`` is user-facing source code. Two failure modes reach the
client as an unreadable one-liner:

1. HTML-escaped quotes (``{"name": "Alice"}`` → ``{&quot;name&quot;: …}``) —
   the client renders a text node, so entities show literally (E2E-05).
2. Collapsed newlines — the model minifies the snippet or double-escapes
   ``\n`` inside the JSON string, so a multi-statement program scrolls
   horizontally as a single line. Partial newlines (a ``def`` line break while
   the body stays glued) must still be repaired — bailing on *any* ``\\n`` left
   comments glued to statements and CSS props spaced on one line.

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
#: Indent-shaped ``\\n`` + spaces/tab — safe even when other real newlines exist
#: (authored ``print("\\n")`` demos lack trailing indent after the escape).
_LITERAL_INDENT_ESCAPES = re.compile(r"\\n([ \t]{2,}|\t)")
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

#: Minified statement glue — semicolon languages.
_STMT_SEMI = re.compile(r";[ \t]+")

#: Long-line threshold: short authored one-liners stay; collapsed bodies exceed it.
_COLLAPSED_LINE_MIN = 72

#: Python statement keywords that start a new statement after a glued comment.
_PY_STMT_HEAD = (
    r"(?:return|print|raise|pass|break|continue|if|for|while|def|class|import|from|"
    r"await|yield|assert|global|nonlocal|try|with|del)\b"
)
#: ``# comment unique_numbers = …`` / ``# comment return …`` / ``# label:name = …``.
_PY_COMMENT_THEN_CODE = re.compile(
    rf"^(?P<comment>#[^\n]*?)"
    rf"(?:"
    rf"(?P<sp>[ \t]+)(?P<stmt>{_PY_STMT_HEAD}.*)"
    rf"|"
    rf"(?P<sp2>[ \t]+)(?P<assign>[a-zA-Z_]\w*[ \t]*=.*)"
    rf"|"
    rf"(?P<colon>:)(?P<glued>[a-zA-Z_]\w*[ \t]*=.*)"
    rf")$"
)
#: ``]result =`` / ``)print(`` — closing delim jammed into the next statement.
_PY_DELIM_THEN_STMT = re.compile(
    rf"(?P<delim>[\)\]\"'])(?P<code>(?:{_PY_STMT_HEAD}|[a-zA-Z_]\w*[ \t]*=))"
)

#: CSS ``prop: value;`` runs on one long line (often inside an HTML ``<style>``).
_CSS_DECLARATION = re.compile(r"[a-zA-Z-]+\s*:\s*[^;{}]+;")


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
    r"""Turn leftover ``\n`` / ``\t`` into real control chars.

    Full expand when the snippet has zero real newlines (classic double-JSON).
    Indent-shaped ``\n`` / ``\t`` expand even alongside real newlines — partial
    decode leaves CSS/Python bodies spaced on one line while tags already wrap.
    """
    if not _LITERAL_ESCAPES.search(content):
        return content
    if "\n" not in content:
        return _LITERAL_ESCAPES.sub(lambda m: _ESCAPE_MAP[m.group(1)], content)
    return _LITERAL_INDENT_ESCAPES.sub(lambda m: "\n" + m.group(1), content)


def _soft_break_markup(content: str) -> str:
    """Insert newlines between adjacent tags; also unminify CSS declaration runs."""
    if "<" not in content and "{" not in content:
        return content
    result = content
    # Always split ``><`` — safe with other newlines; idempotent when already broken.
    if "<" in result:
        result = re.sub(r">\s*<", ">\n<", result)
    return _soft_break_css_runs(result)


def _soft_break_css_runs(content: str) -> str:
    """Break long CSS ``{ prop: v; prop: v; }`` lines (HTML ``<style>`` or ``css``)."""

    def _line(line: str) -> str:
        if len(line) < _COLLAPSED_LINE_MIN or not _CSS_DECLARATION.search(line):
            return line
        if line.count(";") < 1 and "{" not in line:
            return line
        out = re.sub(r"\{\s+", "{\n  ", line)
        out = _STMT_SEMI.sub(";\n  ", out)
        out = re.sub(r"[ \t]+\}", "\n}", out)
        return out

    return "\n".join(_line(line) for line in content.split("\n"))


def _soft_break_python(content: str) -> str:
    """Split jammed ``def``/``class`` headers and comment/statement glue per line."""
    result = content
    if "\n" not in result and len(result) >= 60:
        def_match = _PY_DEF_BODY.search(result)
        if def_match is not None:
            ret = def_match.group("ret")
            header = def_match.group("header") + (f" {ret.strip()}" if ret else "") + ":"
            result = (
                result[: def_match.start()]
                + f"{header}\n    {def_match.group('body')}"
                + result[def_match.end() :]
            )
        else:
            class_match = _PY_CLASS_BODY.search(result)
            if class_match is not None:
                result = (
                    result[: class_match.start()]
                    + f"{class_match.group('header')}:\n    {class_match.group('body')}"
                    + result[class_match.end() :]
                )
    return "\n".join(_repair_python_line(line) for line in result.split("\n"))


def _repair_python_line(line: str) -> str:
    """Unstick ``# comment stmt`` and ``]next =`` glue on a single long line."""
    stripped = line.lstrip()
    comment_glue = stripped.startswith("#") and (
        "=" in stripped or "return" in stripped or "print" in stripped
    )
    if len(line) < _COLLAPSED_LINE_MIN and not comment_glue:
        return line
    current = line
    comment_match = _PY_COMMENT_THEN_CODE.match(current)
    if comment_match is not None:
        comment = comment_match.group("comment")
        if comment_match.group("colon"):
            comment = f"{comment}:"
        stmt = comment_match.group("stmt") or comment_match.group("assign") or comment_match.group("glued")
        if stmt:
            current = f"{comment}\n{stmt}"
    # May still have ``]result =`` / ``)print(`` on the statement line(s).
    parts = current.split("\n")
    return "\n".join(_PY_DELIM_THEN_STMT.sub(r"\g<delim>\n\g<code>", part) for part in parts)


def _soft_break_statements(content: str) -> str:
    """Split ``a; b; c`` — whole snippet or per long line when partially wrapped."""
    if ";" not in content:
        return content
    if "\n" not in content:
        if len(content) < 60:
            return content
        return _STMT_SEMI.sub(";\n", content)

    def _line(line: str) -> str:
        if len(line) < _COLLAPSED_LINE_MIN or ";" not in line:
            return line
        return _STMT_SEMI.sub(";\n", line)

    return "\n".join(_line(line) for line in content.split("\n"))


def normalize_code_content(content: str, *, language: str = "text") -> str:
    """Entity repair + restore readable line structure for collapsed snippets."""
    result = normalize_code_entities(content)
    result = _expand_literal_escapes(result)
    lang = (language or "text").strip().lower()
    if lang in _MARKUP_LANGS or (lang == "text" and result.lstrip().startswith("<!")):
        result = _soft_break_markup(result)
    elif lang in {"css", "scss", "less"}:
        result = _soft_break_css_runs(result)
    if lang in {"python", "py", "python3"}:
        result = _soft_break_python(result)
    if lang in {"javascript", "js", "typescript", "ts", "java", "c", "cpp", "go", "rust"}:
        result = _soft_break_statements(result)
    return result


__all__ = ["normalize_code_content", "normalize_code_entities"]

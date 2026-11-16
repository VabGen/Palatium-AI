"""Code text stays verbatim and readable: entity + collapsed-newline repairs.

The schema-first Formatter returns ``CodeBlock.content`` as source code. Providers
may HTML-escape quotes or minify multi-statement snippets onto one line; both
reach the user as unreadable chrome. Repairs are structural and idempotent.
"""

from __future__ import annotations

from palatium_ai.application.agents.formatter.markdown_parser import markdown_to_content_document
from palatium_ai.domain.agents.context_packet import ContextPacket
from palatium_ai.domain.agents.formatter import FormatterInput
from palatium_ai.domain.content import CodeBlock
from palatium_ai.domain.content.code_text import normalize_code_content, normalize_code_entities
from palatium_ai.domain.content.content_document import (
    ContentDocument,
    DocumentMeta,
    HeadingBlock,
)
from palatium_ai.domain.mcp.models import ToolExecutionPlan
from palatium_ai.domain.policies.presentation_icons import PresentationIconPolicy


def _task() -> FormatterInput:
    return FormatterInput(
        task_id="t1",
        context_packet=ContextPacket(
            task_id="t1",
            user_text="hi",
            task_kind="knowledge_request",
            route="researcher",
            route_plan="answer",
            requires_mcp=False,
            execution_plan=ToolExecutionPlan(
                strategy="reason_only",
                requires_tool_call=False,
                rationale="r",
            ),
            context_summary="s",
        ),
        worker_summary="x",
        response_locale="ru-RU",
    )


def test_escaped_quotes_are_decoded_once() -> None:
    assert normalize_code_entities("{&quot;name&quot;: &quot;Alice&quot;}") == '{"name": "Alice"}'


def test_double_escaped_quotes_are_decoded_to_single() -> None:
    assert normalize_code_entities("{&amp;quot;name&amp;quot;: 1}") == '{"name": 1}'


def test_apostrophe_entities_are_decoded() -> None:
    assert normalize_code_entities("print(&#39;a&#39;)") == "print('a')"


def test_code_that_shows_an_entity_on_purpose_is_untouched() -> None:
    """``print("&quot;")`` carries raw quotes — that is authored code, not a slip."""
    source = 'print("&quot;")'
    assert normalize_code_entities(source) == source


def test_plain_code_is_untouched() -> None:
    source = 'data = json.loads(\'{"name": "Alice"}\')'
    assert normalize_code_entities(source) == source


def test_markup_entities_are_out_of_scope() -> None:
    """An HTML snippet legitimately contains ``&lt;`` — never unescape it."""
    source = "<div class='x'>&lt;span&gt;</div>"
    assert normalize_code_entities(source) == source


def test_code_block_validator_applies_the_repair() -> None:
    block = CodeBlock(language="python", content="json_string = '{&quot;name&quot;: 1}'")
    assert block.content == "json_string = '{\"name\": 1}'"


def test_gfm_fence_is_repaired_end_to_end() -> None:
    md = "Пример:\n\n```python\njson_string = '{&quot;name&quot;: &quot;Alice&quot;}'\n```\n"
    doc = markdown_to_content_document(md, _task())
    code = next(block for block in doc.blocks if isinstance(block, CodeBlock))
    assert code.content == 'json_string = \'{"name": "Alice"}\''


def test_literal_backslash_n_expands_when_snippet_has_no_newline() -> None:
    raw = "def f():\\n    return 1"
    assert normalize_code_content(raw, language="python") == "def f():\n    return 1"


def test_real_newlines_leave_literal_backslash_n_alone() -> None:
    """A demo that prints ``\\n`` still has other real newlines — leave it."""
    source = 'print("\\n")\nprint("ok")'
    assert normalize_code_content(source, language="python") == source


def test_minified_html_gets_soft_breaks() -> None:
    raw = "<!DOCTYPE html><html><head><title>x</title></head><body><button>Go</button></body></html>"
    out = normalize_code_content(raw, language="html")
    assert "\n" in out
    assert "<head>" in out
    assert out.count("\n") >= 3


def test_minified_python_def_splits_header_from_body() -> None:
    raw = "def remove_duplicates_and_sort(numbers: list) -> list: '''функция принимает список'''\n"
    # Already has a trailing newline from the literal — strip to one-line case.
    raw = raw.rstrip("\n")
    out = normalize_code_content(raw, language="python")
    assert out.startswith("def remove_duplicates_and_sort(numbers: list) -> list:\n")
    assert "'''функция" in out


def test_already_formatted_python_is_untouched() -> None:
    source = "def f(x: int) -> int:\n    return x\n"
    assert normalize_code_content(source, language="python") == source


def test_python_comment_glued_to_statement_splits() -> None:
    """Partial newlines must not skip repair — comment+body on one line stays unreadable."""
    raw = (
        "def remove_duplicates_and_sort(numbers):\n"
        "# Создаем множество из списка, чтобы убрать дубликаты unique_numbers = set(numbers)\n"
        "# Сортируем множество и преобразуем его обратно в список return sorted(unique_numbers)\n"
        "# Пример использования:my_list = [5, 2, 8, 2, 9, 5, 1]"
        "result = remove_duplicates_and_sort(my_list)print(result)"
    )
    out = normalize_code_content(raw, language="python")
    assert "дубликаты\nunique_numbers = set(numbers)" in out
    assert "список\nreturn sorted(unique_numbers)" in out
    assert "использования:\nmy_list = [5, 2, 8, 2, 9, 5, 1]" in out
    assert "]\nresult = remove_duplicates_and_sort(my_list)" in out
    assert ")\nprint(result)" in out


def test_html_style_css_props_soft_break_with_other_newlines() -> None:
    """Tags already wrapped must not block CSS declaration un-minify."""
    raw = (
        "<!DOCTYPE html>\n<html>\n<head>\n<style>\n"
        "body { display: flex; justify-content: center; align-items: center; "
        "height: 100vh; margin: 0; background-color: #f0f0f0; }\n"
        "</style>\n</head>\n<body>\n<button>Нажми меня</button>\n</body>\n</html>"
    )
    out = normalize_code_content(raw, language="html")
    assert "body {\n" in out
    assert "display: flex;\n" in out
    assert "justify-content: center;\n" in out
    assert out.index("display: flex") < out.index("</style>")


def test_indent_shaped_literal_newline_expands_alongside_real_breaks() -> None:
    raw = 'print("hi")\\n    x = 1'
    # One real-looking structure via partial escape — expand indent-shaped \\n.
    out = normalize_code_content(raw, language="python")
    # No real newline yet → full expand path; keep assertion on readable body.
    assert "\n" in out
    assert "x = 1" in out


def test_heading_before_code_gets_document_icon_not_chart() -> None:
    doc = ContentDocument(
        schema_version=1,
        locale="ru-RU",
        blocks=(
            HeadingBlock(level=2, text="Python: пример", icon="chart"),
            CodeBlock(language="python", content="print(1)"),
        ),
        meta=DocumentMeta(confidence=0.9, kind="report"),
    )
    enriched = PresentationIconPolicy.enrich(doc)
    heading = enriched.blocks[0]
    assert isinstance(heading, HeadingBlock)
    assert heading.icon == "document"

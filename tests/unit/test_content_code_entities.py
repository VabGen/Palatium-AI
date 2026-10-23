"""Code text stays verbatim: a provider's HTML-escaped quotes are repaired (E2E-05).

The schema-first Formatter returns ``CodeBlock.content`` as source code. Some
providers HTML-escape the quotes inside that string, so the user reads
``{&quot;name&quot;: …}`` instead of ``{"name": …}``; the client renders a text
node and never decodes entities. The repair is structural and idempotent.
"""

from __future__ import annotations

from palatium_ai.application.agents.formatter.markdown_parser import markdown_to_content_document
from palatium_ai.domain.agents.context_packet import ContextPacket
from palatium_ai.domain.agents.formatter import FormatterInput
from palatium_ai.domain.content import CodeBlock
from palatium_ai.domain.content.code_text import normalize_code_entities
from palatium_ai.domain.mcp.models import ToolExecutionPlan


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

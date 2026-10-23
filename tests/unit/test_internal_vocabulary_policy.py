"""Internal contract vocabulary must never reach the user-facing layer (020, 055).

The screenshots that motivated this guard: the answer and the HITL card named our
own payload keys (``attachment_context``, ``prior_context``, ``memory_hints``)
because the payload keys and the prompts taught the model that vocabulary. The
payload/prompt renames remove the priming; this policy is the deterministic guard
that also holds when a model ignores the instruction.
"""

from __future__ import annotations

import pytest

from palatium_ai.application.agents.formatter.answer_delta import emit_answer_deltas
from palatium_ai.application.agents.formatter.parsing import align_formatter_meta
from palatium_ai.application.services.option_synthesizer import OptionSynthesizer
from palatium_ai.application.services.turn_sse_bridge import TurnSseBridge, turn_sse_bridge
from palatium_ai.domain.agents.context_packet import ContextPacket
from palatium_ai.domain.agents.formatter import FormatterInput
from palatium_ai.domain.content import (
    ActionSpec,
    CalloutBlock,
    CodeBlock,
    ContentDocument,
    DocumentMeta,
    ListBlock,
    ListItem,
    ParagraphBlock,
)
from palatium_ai.domain.mcp.models import ToolExecutionPlan
from palatium_ai.domain.policies.assistant_identity import ASSISTANT_NAME
from palatium_ai.domain.policies.internal_vocabulary import (
    INTERNAL_TERM_REPLACEMENTS,
    InternalVocabularyPolicy,
)
from tests.conftest import FakeLLMPort

_LEAKY_HITL_LABEL = "В поле `attachment_context` (загруженные файлы) файл СФУТ 9.03-2025 отсутствует."


def _document(*blocks: object, actions: tuple[ActionSpec, ...] = ()) -> ContentDocument:
    return ContentDocument(
        locale="ru",
        title="Анализ файла",
        blocks=blocks,  # type: ignore[arg-type]
        actions=actions,
        meta=DocumentMeta(confidence=0.6, interaction="choice" if actions else "none"),
    )


def _formatter_input(**overrides: object) -> FormatterInput:
    packet = ContextPacket(
        task_id="t1",
        user_text="возьми из БД и ещё раз прочитай",
        task_kind="knowledge_request",
        route="researcher",
        route_plan="research then format",
        requires_mcp=False,
        candidate_capabilities=(),
        execution_plan=ToolExecutionPlan(
            strategy="reason_only",
            requires_tool_call=False,
            rationale="research",
        ),
        context_summary="A" * 200,
    )
    return FormatterInput(task_id="t1", context_packet=packet, **overrides)  # type: ignore[arg-type]


def test_rewrites_backticked_terms_into_user_words() -> None:
    cleaned = InternalVocabularyPolicy.sanitize_text(_LEAKY_HITL_LABEL)

    assert "attachment_context" not in cleaned
    assert "`" not in cleaned
    assert cleaned == "В поле вложения (загруженные файлы) файл СФУТ 9.03-2025 отсутствует."


def test_rewrites_prior_context_and_memory_hints_phrasing() -> None:
    """Exact wording from the reported HITL card options."""
    cleaned = InternalVocabularyPolicy.sanitize_text(
        "В `prior_context` (история диалога) указано, что анализ невозможен. "
        "В `memory_hints` упоминается, что вы передавали два файла."
    )

    assert InternalVocabularyPolicy.find_terms(cleaned) == ()
    assert "предыдущий ответ" in cleaned
    assert "память о вас" in cleaned


def test_rewrites_user_domain_payload_keys_too() -> None:
    """Renaming keys only moves the jargon the model can quote — both spellings go."""
    cleaned = InternalVocabularyPolicy.sanitize_text("в attached_files пусто, а user_facts молчит")

    assert "attached_files" not in cleaned
    assert "user_facts" not in cleaned
    assert "вложения" in cleaned
    assert "память о вас" in cleaned


def test_drops_traffic_grade_ids_and_keeps_filenames() -> None:
    cleaned = InternalVocabularyPolicy.sanitize_text(
        "Файл attachment:4a742ff9-1111-4222-8333-444455556666:СФУТ.pdf и "
        "attachment:4a742ff9-1111-4222-8333-444455556666, инструмент mcp:platform.read_attachment"
    )

    assert "attachment:" not in cleaned
    assert "mcp:" not in cleaned
    assert "4a742ff9-1111-4222-8333-444455556666" not in cleaned
    assert "СФУТ.pdf" in cleaned
    assert "инструмент" in cleaned


def test_does_not_match_identifiers_that_merely_contain_a_term() -> None:
    """``_`` belongs to the token, so a longer identifier is not partially rewritten."""
    text = "attachment_contextual и my_memory_hints_v2"

    assert InternalVocabularyPolicy.find_terms(text) == ()
    assert InternalVocabularyPolicy.sanitize_text(text) == text


def test_sanitize_is_idempotent_and_allocation_free_when_clean() -> None:
    text = "Файл не приложен к текущему диалогу."
    once = InternalVocabularyPolicy.sanitize_text(text)

    assert once is text
    assert InternalVocabularyPolicy.sanitize_text(once) == once


@pytest.mark.parametrize("term", sorted(INTERNAL_TERM_REPLACEMENTS))
def test_every_known_term_is_rewritten(term: str) -> None:
    cleaned = InternalVocabularyPolicy.sanitize_text(f"поле `{term}` не заполнено")

    assert term not in cleaned
    assert InternalVocabularyPolicy.find_terms(cleaned) == ()


def test_document_sanitizes_blocks_and_action_labels_but_not_code() -> None:
    """Code/formula payload is machine text: rewriting it would corrupt the answer."""
    document = _document(
        ParagraphBlock(text="В `prior_context` указано, что файла нет."),
        CalloutBlock(body="В `attachment_context` файл отсутствует."),
        CodeBlock(language="python", content="memory_hints = attachment_context"),
        actions=(ActionSpec(action_id="choice_1", label=_LEAKY_HITL_LABEL, kind="custom"),),
    )

    cleaned = InternalVocabularyPolicy.sanitize_document(document)

    assert cleaned.blocks[2] == document.blocks[2]
    assert "prior_context" not in str(cleaned.blocks[0])
    assert "attachment_context" not in str(cleaned.blocks[1])
    assert "attachment_context" not in cleaned.actions[0].label
    assert cleaned.actions[0].action_id == "choice_1"
    # Prose is clean; the code fence keeps the user's identifiers (055).
    assert InternalVocabularyPolicy.find_terms(cleaned.blocks[0].text) == ()
    assert InternalVocabularyPolicy.find_terms(cleaned.blocks[1].body) == ()


def test_document_is_returned_unchanged_when_there_is_nothing_to_sanitize() -> None:
    document = _document(ParagraphBlock(text="Файл не приложен к диалогу."))

    assert InternalVocabularyPolicy.sanitize_document(document) is document


def test_align_formatter_meta_is_the_user_facing_boundary() -> None:
    """Every Formatter path (llm / fast / deterministic) funnels through align."""
    document = _document(
        ParagraphBlock(text="В поле `attachment_context` файлы отсутствуют."),
        actions=(ActionSpec(action_id="choice_1", label=_LEAKY_HITL_LABEL, kind="custom"),),
    )

    aligned = align_formatter_meta(document, _formatter_input(requires_user_choice=True))

    assert InternalVocabularyPolicy.find_terms(aligned.plain_text()) == ()
    for action in aligned.actions:
        assert InternalVocabularyPolicy.find_terms(action.label) == ()
    assert aligned.meta.interaction == "choice"


@pytest.mark.asyncio()
async def test_option_synthesizer_labels_and_framing_are_sanitized() -> None:
    """Card labels are user-facing: the synthesizer payload key must not surface."""
    llm = FakeLLMPort(
        '{"framing":"В `prior_context` указано, что файл недоступен:",'
        '"options":[{"action_id":"choice_1","label":"Приложить файл заново"},'
        '{"action_id":"choice_2","label":"Взять файл из БД"}]}'
    )
    synth = OptionSynthesizer(llm)

    result = await synth.synthesize(user_text="что с файлом?", response_locale="ru-RU")

    assert result.framing is not None
    assert InternalVocabularyPolicy.find_terms(result.framing) == ()
    assert "`" not in result.framing
    assert [action.label for action in result.actions] == [
        "Приложить файл заново",
        "Взять файл из БД",
    ]


def test_streamed_answer_deltas_are_sanitized() -> None:
    """``emit_answer_deltas`` is the only funnel for streamed prose — worker drafts
    reach the client through it *before* Formatter, so it carries the guard too."""
    bridge = TurnSseBridge()

    with turn_sse_bridge(bridge):
        emit_answer_deltas("В предоставленных данных (`prior_context`) только выжимка.")

    assert bridge.queue.qsize() == 1
    delta = str(bridge.queue.get_nowait()["delta"])
    assert InternalVocabularyPolicy.find_terms(delta) == ()
    assert "`" not in delta


def test_style_hint_identifier_never_reaches_the_answer() -> None:
    """Live leak: the model named the composition style it was told to follow."""
    cleaned = InternalVocabularyPolicy.sanitize_text(
        "Документ структурирован с использованием разделов и иконок, как того требует стиль `restructure_sections_icons`."
    )

    assert "restructure_sections_icons" not in cleaned
    assert "стиль" not in cleaned
    assert cleaned.startswith("Документ структурирован с использованием разделов и иконок.")


@pytest.mark.parametrize("style", ("brand_sections_icons", "plain_text", "social_reply"))
def test_style_identifier_alone_is_replaced_not_dropped(style: str) -> None:
    """A clause that is *only* a style name is dropped; a bare token keeps a sentence."""
    cleaned = InternalVocabularyPolicy.sanitize_text(f"Оформление: {style}")

    assert style not in cleaned
    assert cleaned.strip() != ""


def test_style_meta_clause_removal_is_idempotent() -> None:
    once = InternalVocabularyPolicy.sanitize_text("Готово, оформил в стиле brand_sections_icons. Текст ниже.")

    assert once == "Готово. Текст ниже."
    assert InternalVocabularyPolicy.sanitize_text(once) == once


@pytest.mark.parametrize(
    "leak, expected",
    (
        ("Меня зовут Formatter. Я здесь, чтобы помочь.", f"Меня зовут {ASSISTANT_NAME}. Я здесь, чтобы помочь."),
        ("Я — Researcher в универсальной платформе.", f"Я — {ASSISTANT_NAME} в универсальной платформе."),
        ("I am a Researcher worker in a platform.", f"I am {ASSISTANT_NAME} in a platform."),
        ("I'm the Critic of this pipeline.", f"I'm {ASSISTANT_NAME} of this pipeline."),
    ),
)
def test_self_identification_with_an_internal_role_is_rewritten(leak: str, expected: str) -> None:
    """Live leak: "как тебя зовут" was answered by the Formatter role prompt."""
    assert InternalVocabularyPolicy.sanitize_text(leak) == expected


def test_role_name_outside_a_self_identification_is_left_alone() -> None:
    """A role word may be genuine document content; rewriting it would corrupt the answer."""
    text = "the researcher found the analyst report"

    assert InternalVocabularyPolicy.sanitize_text(text) == text


def test_stream_holds_the_self_identification_opener_across_a_chunk_boundary() -> None:
    opener = "Меня зовут "

    assert InternalVocabularyPolicy.safe_cut(opener) == 0


def test_page_address_markers_never_reach_the_answer() -> None:
    """Live leak: the model copied ``[[page 1]]`` from the attachment fence verbatim."""
    text = "Полный текст файла «Шаблон обложки (1).docx»\n\n[[page 1]]\n\nфилиал СЭД"

    assert "page" not in InternalVocabularyPolicy.sanitize_text(text).lower()
    assert InternalVocabularyPolicy.sanitize_text(text) == "Полный текст файла «Шаблон обложки (1).docx»\n\nфилиал СЭД"


def test_page_marker_removal_keeps_ordinary_citations() -> None:
    """``[1]`` is our own citation contract — it must survive untouched (070)."""
    text = "Источник: регламент [1], страница 4."

    assert InternalVocabularyPolicy.sanitize_text(text) == text


def test_stream_holds_a_partial_page_marker_across_a_chunk_boundary() -> None:
    """Painting ``[[pa`` would leave the prefix behind once the sanitiser strips it."""
    assert InternalVocabularyPolicy.safe_cut("Отчёт [[page 1") < len("Отчёт [[page 1")


@pytest.mark.parametrize(
    "leak, expected",
    (
        ("- **bold** — Выявлены главные идеи.", "- Выявлены главные идеи."),
        ("1. **none** — Используйте нехлорированную воду.", "1. Используйте нехлорированную воду."),
        ("- **bold:** Выявлены главные идеи.", "- Выявлены главные идеи."),
    ),
)
def test_formatting_keyword_printed_instead_of_applied_is_dropped(leak: str, expected: str) -> None:
    """Live leak: the model echoed our playbook ("a bold label") as the label itself."""
    assert InternalVocabularyPolicy.sanitize_text(leak) == expected


def test_a_real_bold_label_and_a_style_word_in_prose_are_kept() -> None:
    """Only the placeholder shape is a defect; the word inside a sentence is content."""
    text = "**Срок:** 10 дней. None of the files were attached."

    assert InternalVocabularyPolicy.sanitize_text(text) == text


def test_emphasis_field_carrying_a_style_keyword_is_dropped_but_text_survives() -> None:
    document = _document(
        ListBlock(
            items=(
                ListItem(text="Выявлены главные идеи", emphasis="bold"),
                ListItem(text="Используйте нехлорированную воду", emphasis="none"),
                ListItem(text="Срок", emphasis="Срок"),
            )
        )
    )

    cleaned = InternalVocabularyPolicy.sanitize_document(document)

    items = cleaned.blocks[0].items
    assert [item.emphasis for item in items] == [None, None, "Срок"]
    assert items[0].text == "Выявлены главные идеи"


def test_stream_holds_a_style_placeholder_split_across_chunks() -> None:
    """``**bold`` + ``** — text`` in two frames would leak the keyword."""
    assert InternalVocabularyPolicy.safe_cut("Начало. **bold") < len("Начало. **bold")


def test_a_block_that_held_only_a_page_marker_is_dropped() -> None:
    """An empty text is invalid and padded whitespace would fake content (050)."""
    document = _document(
        ParagraphBlock(text="[[page 1]]"),
        ParagraphBlock(text="филиал СЭД"),
        ListBlock(items=(ListItem(text="[[page 2]]"), ListItem(text="[[page 3]]"))),
    )

    cleaned = InternalVocabularyPolicy.sanitize_document(document)

    assert [block.type for block in cleaned.blocks] == ["paragraph"]
    assert cleaned.blocks[0].text == "филиал СЭД"


def test_streamed_block_of_pure_notation_is_not_painted() -> None:
    assert InternalVocabularyPolicy.sanitize_block(ParagraphBlock(text="[[page 1]]")) is None
    kept = InternalVocabularyPolicy.sanitize_block(ParagraphBlock(text="Итог: [[page 1]]"))
    assert kept is not None
    assert kept.text == "Итог:"

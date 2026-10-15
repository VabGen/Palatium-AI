"""Intent classifier parses grounding with safe defaults."""

from palatium_ai.application.agents.intent_classifier.parsing import parse_classifier_output


def test_parse_grounding_optional_default() -> None:
    raw = """{"task_kind":"knowledge_request","requires_mcp":false,
    "underspecification_kind":"none","candidate_capabilities":["analyze"],
    "confidence":0.9,"reasoning":"compare clouds"}"""
    out = parse_classifier_output(raw)
    assert out.grounding == "optional"


def test_parse_grounding_compose_defaults_none() -> None:
    raw = """{"task_kind":"knowledge_request","requires_mcp":false,
    "underspecification_kind":"none","candidate_capabilities":["compose"],
    "confidence":0.9,"reasoning":"joke"}"""
    out = parse_classifier_output(raw)
    assert out.grounding == "none"


def test_parse_explicit_required() -> None:
    raw = """{"task_kind":"knowledge_request","requires_mcp":false,
    "underspecification_kind":"none","candidate_capabilities":[],
    "grounding":"required","grounding_reason":"needs file",
    "confidence":0.95,"reasoning":"file ask"}"""
    out = parse_classifier_output(raw)
    assert out.grounding == "required"
    assert "file" in out.grounding_reason


def test_parse_transformation_expand() -> None:
    raw = """{"task_kind":"knowledge_request","requires_mcp":false,
    "underspecification_kind":"none","candidate_capabilities":["expand"],
    "grounding":"none","transformation":"expand",
    "confidence":0.9,"reasoning":"expand prior"}"""
    out = parse_classifier_output(raw)
    assert out.transformation == "expand"


def test_parse_transformation_defaults_none() -> None:
    raw = """{"task_kind":"knowledge_request","requires_mcp":false,
    "underspecification_kind":"none","candidate_capabilities":[],
    "confidence":0.9,"reasoning":"plain ask"}"""
    out = parse_classifier_output(raw)
    assert out.transformation == "none"

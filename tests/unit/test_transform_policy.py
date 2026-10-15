"""TransformPolicy — expand/shorten/rewrite vs restructure routing."""

from palatium_ai.domain.policies.transform import TransformPolicy


def test_coerce_defaults_to_none() -> None:
    assert TransformPolicy.coerce(None) == "none"
    assert TransformPolicy.coerce("bogus") == "none"
    assert TransformPolicy.coerce("expand") == "expand"


def test_content_transforms_need_reason() -> None:
    assert TransformPolicy.needs_reason_over_prior("expand") is True
    assert TransformPolicy.needs_reason_over_prior("shorten") is True
    assert TransformPolicy.needs_reason_over_prior("rewrite") is True
    assert TransformPolicy.needs_reason_over_prior("restructure") is False
    assert TransformPolicy.needs_reason_over_prior("none") is False


def test_format_route_expand_not_format_only() -> None:
    d = TransformPolicy.decide_format_route(transformation="expand")
    assert d.format_only is False
    assert "expand" in d.reason


def test_format_route_restructure_is_format_only() -> None:
    d = TransformPolicy.decide_format_route(transformation="restructure")
    assert d.format_only is True


def test_merge_capability_adds_tag() -> None:
    caps = TransformPolicy.merge_capability(("summarize",), "expand")
    assert "expand" in caps
    assert "summarize" in caps

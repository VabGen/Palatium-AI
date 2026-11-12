"""Runtime must import eval prompt hashing without test fixtures (Docker)."""

from __future__ import annotations


def test_prompt_version_for_role_does_not_require_cassette_fixtures() -> None:
    """Regression 2026-11-11: Harness.call_llm died on missing tests/fixtures/llm."""
    from palatium_ai.application.agents.harness import _prompt_version_for_role

    version = _prompt_version_for_role("formatter")
    assert version == "unknown" or len(version) == 16


def test_cassette_import_does_not_resolve_root_eagerly() -> None:
    """Loading cassette.py must succeed even before fixtures are present."""
    import importlib

    import palatium_ai.application.agents.evals.cassette as cassette_module

    reloaded = importlib.reload(cassette_module)
    assert reloaded._CASSETTE_ROOT is None

# tests/unit/test_filesystem_agents_md.py

"""CMD2 FilesystemAgentsMdLoader + ContextBuilder project_agents_md key."""

from __future__ import annotations

from pathlib import Path

import pytest

from palatium_ai.application.services.context_builder import ContextBuilder
from palatium_ai.infrastructure.project_context.filesystem_agents_md import FilesystemAgentsMdLoader


def test_loader_reads_and_caches(tmp_path: Path) -> None:
    agents = tmp_path / "AGENTS.md"
    agents.write_text("# Contract\n\nPrefer HITL.\n", encoding="utf-8")
    loader = FilesystemAgentsMdLoader(relative_path="AGENTS.md", base_dir=tmp_path, max_chars=8000)
    body1 = loader.load_agents_md()
    assert "Prefer HITL" in body1
    digest1 = loader.agents_md_content_hash()
    assert len(digest1) == 64
    body2 = loader.load_agents_md()
    assert body2 == body1
    assert loader.agents_md_content_hash() == digest1


def test_loader_missing_file_is_empty(tmp_path: Path) -> None:
    loader = FilesystemAgentsMdLoader(relative_path="AGENTS.md", base_dir=tmp_path)
    assert loader.load_agents_md() == ""
    assert loader.agents_md_content_hash() == ""


def test_loader_disabled_returns_empty(tmp_path: Path) -> None:
    (tmp_path / "AGENTS.md").write_text("rules", encoding="utf-8")
    loader = FilesystemAgentsMdLoader(relative_path="AGENTS.md", base_dir=tmp_path, enabled=False)
    assert loader.load_agents_md() == ""


def test_loader_rejects_non_allowlisted_basename(tmp_path: Path) -> None:
    sneaky = tmp_path / "SOUL.md"
    sneaky.write_text("nope", encoding="utf-8")
    loader = FilesystemAgentsMdLoader(relative_path="SOUL.md", base_dir=tmp_path)
    assert loader.load_agents_md() == ""


def test_loader_truncates(tmp_path: Path) -> None:
    (tmp_path / "AGENTS.md").write_text("x" * 5000, encoding="utf-8")
    loader = FilesystemAgentsMdLoader(relative_path="AGENTS.md", base_dir=tmp_path, max_chars=1000)
    body = loader.load_agents_md()
    assert len(body) == 1000


@pytest.mark.asyncio()
async def test_context_builder_project_agents_md_key(tmp_path: Path) -> None:
    (tmp_path / "AGENTS.md").write_text("stable rules", encoding="utf-8")
    loader = FilesystemAgentsMdLoader(relative_path="AGENTS.md", base_dir=tmp_path)
    builder = ContextBuilder(project_context=loader)
    ctx = await builder.build(["project_agents_md"], thread_id="t1")
    assert ctx["project_agents_md"] == "stable rules"


@pytest.mark.asyncio()
async def test_context_builder_missing_agents_md_empty() -> None:
    builder = ContextBuilder(project_context=None)
    ctx = await builder.build(["project_agents_md"], thread_id="t1")
    assert ctx["project_agents_md"] == ""

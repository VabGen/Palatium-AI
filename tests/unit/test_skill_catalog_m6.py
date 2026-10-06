# tests/unit/test_skill_catalog_m6.py

"""Wave M6 — procedural skills progressive disclosure."""

from __future__ import annotations

import json

from pathlib import Path

import pytest

from palatium_ai.application.services.context_builder import ContextBuilder
from palatium_ai.domain.skills.frontmatter import is_safe_skill_name, parse_skill_frontmatter
from palatium_ai.infrastructure.knowledge.in_memory_knowledge_port import InMemoryKnowledgePort
from palatium_ai.infrastructure.mcp.platform_tool_handler import PlatformToolHandler
from palatium_ai.infrastructure.skills.filesystem_skill_catalog import FilesystemSkillCatalog


@pytest.fixture()
def procedural_root(tmp_path: Path) -> Path:
    skill_dir = tmp_path / "alpha-skill"
    skill_dir.mkdir()
    (skill_dir / "SKILL.md").write_text(
        "---\nname: alpha-skill\ndescription: Alpha procedural card for tests.\n---\n\n# Alpha\n\nBody.\n",
        encoding="utf-8",
    )
    (skill_dir / "reference.md").write_text("# Alpha reference\n\nDetail line.\n", encoding="utf-8")
    return tmp_path


def test_parse_skill_frontmatter() -> None:
    name, desc, body = parse_skill_frontmatter(
        "---\nname: demo\ndescription: Demo skill.\n---\n\nBody text\n"
    )
    assert name == "demo"
    assert desc == "Demo skill."
    assert "Body" in body
    assert is_safe_skill_name("demo")
    assert not is_safe_skill_name("../etc")


def test_catalog_lists_summaries_not_bodies(procedural_root: Path) -> None:
    catalog = FilesystemSkillCatalog((str(procedural_root),), base_dir=procedural_root)
    summaries = catalog.list_summaries()
    assert len(summaries) == 1
    assert summaries[0].name == "alpha-skill"
    assert summaries[0].has_reference is True
    text = catalog.format_catalog(max_chars=2000)
    assert "alpha-skill" in text
    assert "Detail line" not in text
    assert "Body" not in text


def test_get_reference_loads_reference_md(procedural_root: Path) -> None:
    catalog = FilesystemSkillCatalog((str(procedural_root),), base_dir=procedural_root)
    doc = catalog.get_reference("alpha-skill")
    assert doc is not None
    assert doc.kind == "reference"
    assert "Detail line" in doc.content


def test_duplicate_name_keeps_first(tmp_path: Path) -> None:
    for folder, desc in (("one", "First copy."), ("two", "Second copy.")):
        d = tmp_path / folder
        d.mkdir()
        (d / "SKILL.md").write_text(
            f"---\nname: dup-skill\ndescription: {desc}\n---\n\n# x\n",
            encoding="utf-8",
        )
    catalog = FilesystemSkillCatalog((str(tmp_path),), base_dir=tmp_path)
    summaries = catalog.list_summaries()
    assert len(summaries) == 1
    assert summaries[0].description == "First copy."


def test_rejects_agent_dx_root(tmp_path: Path) -> None:
    agent = tmp_path / ".agent"
    agent.mkdir()
    (agent / "MEMORY.md").write_text("# dx only\n", encoding="utf-8")
    skill = agent / "fake"
    skill.mkdir()
    (skill / "SKILL.md").write_text(
        "---\nname: leaked\ndescription: Must not load.\n---\n\n# no\n",
        encoding="utf-8",
    )
    catalog = FilesystemSkillCatalog((str(agent),), base_dir=tmp_path)
    assert catalog.list_summaries() == ()


@pytest.mark.asyncio()
async def test_context_builder_skill_catalog_key(procedural_root: Path) -> None:
    catalog = FilesystemSkillCatalog((str(procedural_root),), base_dir=procedural_root)
    builder = ContextBuilder(skill_catalog=catalog, skill_catalog_max_chars=2000)
    ctx = await builder.build(["skill_catalog"], thread_id="t1")
    assert "alpha-skill" in ctx["skill_catalog"]
    empty = await ContextBuilder().build(["skill_catalog"], thread_id="t1")
    assert empty["skill_catalog"] == "(no procedural skills)"


@pytest.mark.asyncio()
async def test_skill_reference_mcp_tool(procedural_root: Path) -> None:
    catalog = FilesystemSkillCatalog((str(procedural_root),), base_dir=procedural_root)
    handler = PlatformToolHandler(
        knowledge_port=InMemoryKnowledgePort(),
        skill_catalog=catalog,
    )
    result = await handler.call_tool("skill_reference", {"name": "alpha-skill"})
    assert result.is_error is False
    payload = json.loads(result.content[0]["text"])
    assert payload["name"] == "alpha-skill"
    assert "Detail line" in payload["content"]

    missing = await handler.call_tool("skill_reference", {"name": "nope"})
    assert missing.is_error is True


def test_repo_procedural_skills_load() -> None:
    """Ship-with-repo skills under skills/procedural/ are valid."""
    root = Path.cwd() / "skills" / "procedural"
    if not root.is_dir():
        pytest.skip("skills/procedural not present")
    catalog = FilesystemSkillCatalog((str(root),), base_dir=Path.cwd())
    names = {s.name for s in catalog.list_summaries()}
    assert "memory-os-write" in names
    assert "hitl-irreversible" in names
    ref = catalog.get_reference("memory-os-write")
    assert ref is not None
    assert ref.kind == "reference"

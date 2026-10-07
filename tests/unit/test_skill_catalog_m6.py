# tests/unit/test_skill_catalog_m6.py

"""Wave M6 — procedural skills progressive disclosure."""

from __future__ import annotations

import json

from pathlib import Path

import pytest

from palatium_ai.application.agents.skill_hydrate import hydrate_skill_references
from palatium_ai.application.services.context_builder import ContextBuilder
from palatium_ai.application.tools.executor import ToolExecutor
from palatium_ai.domain.agents.agent_config import AgentConfig
from palatium_ai.domain.agents.contracts import AgentContext
from palatium_ai.domain.skills.frontmatter import is_safe_skill_name, parse_skill_frontmatter
from palatium_ai.domain.skills.select import parse_skill_catalog_entries, select_skills_by_overlap
from palatium_ai.infrastructure.knowledge.in_memory_knowledge_port import InMemoryKnowledgePort
from palatium_ai.infrastructure.mcp.platform_tool_handler import PlatformToolHandler
from palatium_ai.infrastructure.skills.filesystem_skill_catalog import FilesystemSkillCatalog


def _write_skill(
    root: Path,
    name: str,
    *,
    description: str = "Use when testing procedural skill loading.",
    version: str = "1.0.0",
    body: str = "# Body\n",
    reference: str | None = None,
    folder: str | None = None,
) -> Path:
    skill_dir = root / (folder or name)
    skill_dir.mkdir(parents=True, exist_ok=True)
    (skill_dir / "SKILL.md").write_text(
        f"---\nname: {name}\nversion: {version}\ndescription: {description}\n---\n\n{body}",
        encoding="utf-8",
    )
    if reference is not None:
        (skill_dir / "reference.md").write_text(reference, encoding="utf-8")
    return skill_dir


@pytest.fixture()
def procedural_root(tmp_path: Path) -> Path:
    _write_skill(
        tmp_path,
        "alpha-skill",
        description="Use when testing alpha procedural disclosure.",
        body="# Alpha\n\nBody.\n",
        reference="# Alpha reference\n\nDetail line.\n",
    )
    return tmp_path


def test_parse_skill_frontmatter() -> None:
    parsed = parse_skill_frontmatter("---\nname: demo\nversion: 1.2.3\ndescription: Demo skill.\n---\n\nBody text\n")
    assert parsed.name == "demo"
    assert parsed.version == "1.2.3"
    assert parsed.description == "Demo skill."
    assert "Body" in parsed.body
    assert is_safe_skill_name("demo")
    assert not is_safe_skill_name("../etc")


def test_parse_skill_frontmatter_requires_version() -> None:
    with pytest.raises(ValueError, match="version"):
        parse_skill_frontmatter("---\nname: demo\ndescription: Demo skill.\n---\n\nBody\n")


def test_catalog_lists_summaries_not_bodies(procedural_root: Path) -> None:
    catalog = FilesystemSkillCatalog((str(procedural_root),), base_dir=procedural_root)
    summaries = catalog.list_summaries()
    assert len(summaries) == 1
    assert summaries[0].name == "alpha-skill"
    assert summaries[0].version == "1.0.0"
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


def test_get_reference_falls_back_to_skill_body(tmp_path: Path) -> None:
    _write_skill(tmp_path, "body-only", body="# Only body\n\nChecklist item.\n")
    catalog = FilesystemSkillCatalog((str(tmp_path),), base_dir=tmp_path)
    doc = catalog.get_reference("body-only")
    assert doc is not None
    assert doc.kind == "skill_body"
    assert "Checklist item" in doc.content
    assert "name: body-only" not in doc.content


def test_duplicate_name_keeps_first(tmp_path: Path) -> None:
    first = tmp_path / "a"
    second = tmp_path / "b"
    first.mkdir()
    second.mkdir()
    # Nested folders named after skill id (spec: parent dir == name).
    _write_skill(first, "dup-skill", description="First copy.")
    _write_skill(second, "dup-skill", description="Second copy.")
    catalog = FilesystemSkillCatalog((str(tmp_path),), base_dir=tmp_path)
    summaries = catalog.list_summaries()
    assert len(summaries) == 1
    assert summaries[0].description == "First copy."


def test_skips_name_folder_mismatch(tmp_path: Path) -> None:
    _write_skill(tmp_path, "real-name", folder="wrong-folder")
    catalog = FilesystemSkillCatalog((str(tmp_path),), base_dir=tmp_path)
    assert catalog.list_summaries() == ()


def test_skips_skill_md_at_scan_root(tmp_path: Path) -> None:
    (tmp_path / "SKILL.md").write_text(
        "---\nname: root-skill\nversion: 1.0.0\ndescription: Must not load.\n---\n\n# no\n",
        encoding="utf-8",
    )
    catalog = FilesystemSkillCatalog((str(tmp_path),), base_dir=tmp_path)
    assert catalog.list_summaries() == ()


def test_skips_missing_or_invalid_skill_md(tmp_path: Path) -> None:
    empty = tmp_path / "empty-dir"
    empty.mkdir()
    broken = tmp_path / "broken-skill"
    broken.mkdir()
    (broken / "SKILL.md").write_text("not frontmatter\n", encoding="utf-8")
    catalog = FilesystemSkillCatalog((str(tmp_path),), base_dir=tmp_path)
    assert catalog.list_summaries() == ()
    assert catalog.get_reference("missing") is None


def test_rejects_agent_dx_root(tmp_path: Path) -> None:
    agent = tmp_path / ".agent"
    agent.mkdir()
    (agent / "MEMORY.md").write_text("# dx only\n", encoding="utf-8")
    _write_skill(agent, "leaked", description="Must not load.")
    catalog = FilesystemSkillCatalog((str(agent),), base_dir=tmp_path)
    assert catalog.list_summaries() == ()


def test_select_skills_by_overlap() -> None:
    entries = (
        ("memory-os-write", "Use when implementing durable memory Write paths."),
        ("hitl-irreversible", "Use when reviewing irreversible EDMS write paths."),
    )
    picked = select_skills_by_overlap(
        "Please review how we Write durable memory entries",
        entries,
        limit=2,
    )
    assert picked[0] == "memory-os-write"
    catalog = "Procedural skills:\n- memory-os-write [+ref]: Use when implementing durable memory Write paths.\n"
    assert parse_skill_catalog_entries(catalog) == (
        ("memory-os-write", "Use when implementing durable memory Write paths."),
    )


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


@pytest.mark.asyncio()
async def test_hydrate_skill_references_via_mcp(procedural_root: Path) -> None:
    catalog = FilesystemSkillCatalog((str(procedural_root),), base_dir=procedural_root)

    class _Reg:
        def list_servers(self) -> list[str]:
            return ["platform"]

        async def list_tools(self, server_name: str) -> list[object]:
            return []

        async def list_tool_summaries(self, server_name: str) -> list[object]:
            return []

        async def get_tool(self, server_name: str, tool_name: str) -> object | None:
            return None

        async def call_tool(
            self,
            server_name: str,
            tool_call: object,
            *,
            allow_unpinned: bool = False,
        ) -> object:
            from palatium_ai.domain.mcp.models import MCPToolResult

            assert server_name == "platform"
            name = getattr(tool_call, "arguments", {}).get("name", "")
            doc = catalog.get_reference(str(name))
            assert doc is not None
            return MCPToolResult(
                content=[
                    {
                        "type": "text",
                        "text": json.dumps(
                            {
                                "tool": "skill_reference",
                                "name": doc.name,
                                "kind": doc.kind,
                                "truncated": doc.truncated,
                                "content": doc.content,
                            }
                        ),
                    }
                ],
                is_error=False,
            )

    config = AgentConfig(
        name="coder",
        role="coder",
        model_tier="mid",
        allowed_tools=("mcp:platform.skill_reference",),
    )
    text = await hydrate_skill_references(
        catalog_text=catalog.format_catalog(max_chars=2000),
        user_text="testing alpha procedural disclosure path",
        tool_executor=ToolExecutor(config),
        mcp_registry=_Reg(),  # type: ignore[arg-type]
        context=AgentContext(thread_id="t1"),
    )
    assert "skill:alpha-skill" in text
    assert "Detail line" in text


def test_repo_procedural_skills_load() -> None:
    """Ship-with-repo skills under skills/procedural/ are valid."""
    root = Path.cwd() / "skills" / "procedural"
    if not root.is_dir():
        pytest.skip("skills/procedural not present")
    catalog = FilesystemSkillCatalog((str(root),), base_dir=Path.cwd())
    names = {s.name for s in catalog.list_summaries()}
    assert "memory-os-write" in names
    assert "hitl-irreversible" in names
    assert all(s.version for s in catalog.list_summaries())
    ref = catalog.get_reference("memory-os-write")
    assert ref is not None
    assert ref.kind == "reference"
    assert Path("skills/SKILL.md").exists() is False

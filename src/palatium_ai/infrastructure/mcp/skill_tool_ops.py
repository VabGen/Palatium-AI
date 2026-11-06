# src/palatium_ai/infrastructure/mcp/skill_tool_ops.py

"""In-process skill MCP ops: ``skill_reference`` (M6) + ``skill_manage`` (CMD4)."""

from __future__ import annotations

import json

from typing import TYPE_CHECKING, cast

from palatium_ai.core.logging import get_logger
from palatium_ai.domain.mcp.models import MCPToolResult
from palatium_ai.domain.skills.frontmatter import is_safe_skill_name
from palatium_ai.domain.skills.lint import lint_skill_markdown

if TYPE_CHECKING:
    from palatium_ai.domain.skills.port import SkillCatalogPort, WritableSkillCatalogPort

logger = get_logger(__name__)

_VALID_ACTIONS = frozenset({"create", "update", "delete"})
_FEATURE_DISABLED = "Feature disabled"


async def skill_reference(
    catalog: SkillCatalogPort | None,
    arguments: dict[str, object],
) -> MCPToolResult:
    if catalog is None:
        return _error_result("skill_reference unavailable: skill catalog not configured")
    name = arguments.get("name")
    if not isinstance(name, str) or not name.strip():
        return _error_result("Invalid params: name is required")
    doc = catalog.get_reference(name.strip())
    if doc is None:
        return _error_result(f"Unknown skill: {name.strip()}")
    payload = {
        "tool": "skill_reference",
        "name": doc.name,
        "kind": doc.kind,
        "truncated": doc.truncated,
        "content": doc.content,
    }
    return MCPToolResult(
        content=[{"type": "text", "text": json.dumps(payload, ensure_ascii=False)}],
        is_error=False,
    )


async def skill_manage(
    catalog: SkillCatalogPort | None,
    arguments: dict[str, object],
    *,
    enabled: bool,
) -> MCPToolResult:
    """Create/update/delete a product skill (HITL outside; lint + flag gated)."""
    if not enabled:
        return _error_result(_FEATURE_DISABLED)
    gate = _prepare_manage(catalog, arguments)
    if isinstance(gate, MCPToolResult):
        return gate
    writable, action, skill_name, content = gate
    if action == "delete":
        return await _delete_skill(writable, skill_name=skill_name)
    return await _upsert_skill(
        catalog,
        writable,
        action=action,
        skill_name=skill_name,
        content=content,
    )


def _prepare_manage(
    catalog: SkillCatalogPort | None,
    arguments: dict[str, object],
) -> tuple[WritableSkillCatalogPort, str, str, str] | MCPToolResult:
    if catalog is None:
        return _error_result("skill_manage unavailable: skill catalog not configured")
    writable = _as_writable(catalog)
    if writable is None:
        return _error_result("skill_manage unavailable: catalog is read-only")

    action_raw = arguments.get("action")
    if not isinstance(action_raw, str) or action_raw.strip().lower() not in _VALID_ACTIONS:
        return _error_result("Invalid params: action must be create|update|delete")
    action = action_raw.strip().lower()

    skill_name_raw = arguments.get("skill_name")
    if not isinstance(skill_name_raw, str) or not skill_name_raw.strip():
        return _error_result("Invalid params: skill_name is required")
    skill_name = skill_name_raw.strip()
    if not is_safe_skill_name(skill_name):
        return _error_result("Invalid params: skill_name must match [a-z0-9][a-z0-9_-]{0,63}")

    content_raw = arguments.get("content", "")
    content = content_raw if isinstance(content_raw, str) else ""
    if action in {"create", "update"}:
        description_raw = arguments.get("description", "")
        description = description_raw.strip() if isinstance(description_raw, str) else ""
        lint = lint_skill_markdown(
            content,
            expected_name=skill_name,
            expected_description=description or None,
        )
        if not lint.ok:
            return _error_result("skill lint failed: " + "; ".join(lint.errors))
    return writable, action, skill_name, content


async def _upsert_skill(
    catalog: SkillCatalogPort,
    writable: WritableSkillCatalogPort,
    *,
    action: str,
    skill_name: str,
    content: str,
) -> MCPToolResult:
    existing = catalog.get_reference(skill_name)
    if action == "create" and existing is not None:
        return _error_result(f"skill already exists: {skill_name} (use action=update)")
    if action == "update" and existing is None:
        return _error_result(f"skill not found: {skill_name} (use action=create)")

    try:
        summary = writable.upsert_skill(name=skill_name, content=content)
    except ValueError as exc:
        return _error_result(str(exc))
    except OSError as exc:
        logger.warning("skill_manage.write_failed", name=skill_name, error=str(exc))
        return _error_result(f"filesystem write failed: {exc}")

    logger.info("skill_managed", action=action, name=summary.name, version=summary.version)
    payload = {
        "tool": "skill_manage",
        "action": action,
        "name": summary.name,
        "version": summary.version,
        "description": summary.description,
        "status": "saved",
    }
    return MCPToolResult(
        content=[{"type": "text", "text": json.dumps(payload, ensure_ascii=False)}],
        is_error=False,
    )


async def _delete_skill(writable: WritableSkillCatalogPort, *, skill_name: str) -> MCPToolResult:
    try:
        deleted = writable.delete_skill(name=skill_name)
    except ValueError as exc:
        return _error_result(str(exc))
    except OSError as exc:
        logger.warning("skill_manage.delete_failed", name=skill_name, error=str(exc))
        return _error_result(f"filesystem delete failed: {exc}")
    if not deleted:
        return _error_result(f"skill not found: {skill_name}")
    logger.info("skill_managed", action="delete", name=skill_name)
    payload = {
        "tool": "skill_manage",
        "action": "delete",
        "name": skill_name,
        "status": "deleted",
    }
    return MCPToolResult(
        content=[{"type": "text", "text": json.dumps(payload, ensure_ascii=False)}],
        is_error=False,
    )


def _as_writable(catalog: SkillCatalogPort) -> WritableSkillCatalogPort | None:
    upsert = getattr(catalog, "upsert_skill", None)
    delete = getattr(catalog, "delete_skill", None)
    if upsert is None or delete is None:
        return None
    return cast("WritableSkillCatalogPort", catalog)


def _error_result(message: str) -> MCPToolResult:
    return MCPToolResult(
        content=[{"type": "text", "text": json.dumps({"error": message}, ensure_ascii=False)}],
        is_error=True,
    )

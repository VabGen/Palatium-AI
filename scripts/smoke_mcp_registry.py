"""One-shot: registry tools/list against local stubs (uses env/.env auth)."""

from __future__ import annotations

import asyncio


async def _run() -> int:
    from palatium_ai.core.config.settings import get_settings
    from palatium_ai.infrastructure.mcp.registry import MCPRegistry

    settings = get_settings()
    token_set = bool(settings.mcp.resolve_auth_token("edms"))
    print(f"auth_token_configured={token_set}")
    registry = MCPRegistry(settings)
    await registry.initialize()
    try:
        for name in ("edms", "analytics"):
            tools = await registry.list_tools(name)
            print(f"{name}: {[tool.name for tool in tools]}")
            if not tools:
                return 1
    finally:
        await registry.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(_run()))

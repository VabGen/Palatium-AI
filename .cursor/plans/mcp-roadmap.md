# MCP — полный план (канон)

Обновлено: 2026-09-04. Источник истины для MCP-волн Host/stubs/gateway.
EDMS-адаптер Канцлера — отдельный трек: скилл `edms-mcp-max-pro` (092).
При противоречии с правилами 070/020/090/092 — **правила побеждают**.

## North star

```
Host (main.py :8000) = MCP client only
  FastAPI · LangGraph · Harness · ToolRegistry · HITL · pins · audit
  MCPRegistry
    ├── platform  → discovery: static pins (SoT) · execute: PlatformToolHandler
    ├── edms      → HTTP FastMCP :8080 (discovery + execute)
    └── analytics → HTTP FastMCP :8081 (discovery + execute)

optional gateway (profile mcp-gateway): ProxyProvider edms|analytics only
platform NEVER proxied
```

- `main.py` **не** God-процесс и **не** стартует 8080/8081.
- Control plane (pins, HITL, ACL, argument_policy, actor bind) — **только Host**.
- Domain servers (edms/analytics) — FastMCP Streamable HTTP + JWT `aud=mcp:<server>`.

Опора: [MCP intro](https://modelcontextprotocol.io/docs/2026-07-28/getting-started/intro),
[FastMCP](https://gofastmcp.com/getting-started/welcome).

---

## Track A — Foundation (Phases 1–6) · DONE

| Phase | Цель | Статус | Ключевой результат |
|-------|------|--------|-------------------|
| **1** | Один транспорт FastMCP HTTP | **DONE** | `fastmcp==4.0.0`; stubs Streamable HTTP; Host `Client(mode=auto)` |
| **2** | Один path execute platform | **DONE** | stub discovery-only refuse; `PlatformHandlerNotWiredError`; no fake write |
| **3** | Auth 2026 JWT audience | **DONE** | `aud=mcp:<server>`; MultiAuth JWT+static; `MCP_AUTH_REQUIRED` |
| **4** | Единый schema SoT | **DONE** | `domain/mcp/*_schemas.py`; удалены `contract.py` / `schema_util` |
| **5** | Host control plane harden | **DONE** | registry pin gate; `argument_policy` в `call_mcp_tool`; strip annotations |
| **6** | Gateway scaffold | **DONE** | `mcp_servers/gateway/` ProxyProvider + pin allowlist; platform excluded |

**Не переизобретать.** Следующая работа — Track C (EDMS), не «Phase 1/B снова».

---

## Track B — Platform local discovery (убрать :8082) · DONE

**Проблема (была):** Compose `MCP_SERVERS` = edms+analytics only →
`is_registered("platform")==False` → `_wire_platform_handler` skip → 070 tools «пропали»
без fail-loud (`assert_local_handlers_wired` смотрит только `_servers`).

**Канон: вариант A** (не B in-process FastMCP на Host):

- Discovery platform = `platform_schemas` + `iter_platform_pins()` / fingerprints.
- Execute = всегда `PlatformToolHandler` если `requires_local_handler("platform")`.
- `MCP_SERVERS` = **только remote** `{edms, analytics}`.
- URL `platform` в env/Consul → **warn + ignore**.
- Stub `mcp_servers/platform/` — optional (`dev-up -WithPlatformStub`), не Host runtime.

| Wave | Что | DoD | Статус |
|------|-----|-----|--------|
| **B1** Contract | `has_local_capability`; handler wire безусловно | unit + assert | **DONE** |
| **B2** Registry | `list_tools(platform)` offline; local `call_tool` | без :8082 | **DONE** |
| **B3** Compose / env | examples без platform URL | паритет Compose/Poetry | **DONE** |
| **B4** Dev scripts | `dev-up` без platform; `-WithPlatformStub` | optional stub | **DONE** |
| **B5** Docs / 070 | Host-local platform; убран phantom `mcp.server` | 070 ↔ код | **DONE** |
| **B6** Optional | stub marked external-discovery-only | **DONE** |

**Уточнения (закрыты):**

1. `assert_local_handlers_wired` — по `LOCAL_EXECUTION_SERVERS`.
2. `list_servers` / capability index — platform всегда в discovery.
3. Env examples: `.env.example`, local/staging/prod/cloud.
4. `tool_policy` onboarding: platform = pin + handler, не URL.

---

## Track C — EDMS real adapter · IN PROGRESS (W0 done)

Скилл: `edms-mcp-max-pro` · правило **092** · волны W0–W7 в `waves.md`.

- **W0** inventory **DONE** (2026-09-04): stub 2 tools; pins/HITL; gateway allowlist;
  JavaEdms local (gitignored); legacy AI-Assistant **не передан**.
- Next: **W1** contracts — после legacy-файлов и ответа: какой API = `search_documents` /
  `archive_document` (кандидаты: `FullSearchController`, `DocumentController GET`,
  archive ≠ `api/nces` registration blindly).
- Legacy AI-Assistant / junior-код = сырьё INGEST, не эталон.
- Логика СЭД = JavaEdms **read-only** или вопрос пользователю (не выдумывать API).

Gateway: `MCP_UPSTREAM_URL` на stub сегодня → real MCP adapter после контрактов.

---

## Инварианты (чеклист после любой волны)

- [ ] Агент не зовёт HTTP/БД мимо MCP/Harness
- [ ] `platform` tools/call **никогда** не уходит на remote stub
- [ ] edms/analytics tools/call = HTTP MCP + Host pins + HITL
- [ ] Compose и Poetry = один набор platform capabilities
- [ ] Новый platform tool = schema SoT → pin → handler → `allowed_tools` (не stub-first)
- [ ] `main.py` не стартует 8080/8081
- [ ] Gateway never proxies platform

## Анти-идеалы

| Искушение | Почему нет |
|-----------|------------|
| Всё через один FastMCP в `main.py` | God process, ломает периметр |
| Проксировать platform через gateway | memory/graph вне Host control plane |
| Держать :8082 «для симметрии» | auth/тайминг/stale process |
| Discovery из stub, execute local без sync pins | fingerprint drift |
| Вариант B (in-process FastMCP platform) как канон | дубль SoT; A достаточен |
| Чинить Docker ad-hoc `if env` | снова профиль-зависимость |

## Где править (карта)

| Нужно | Куда |
|-------|------|
| Registry / bootstrap platform | `infrastructure/mcp/registry.py`, `application/bootstrap.py` |
| Pins / schemas | `domain/mcp/tool_policy.py`, `platform_schemas.py`, `external_schemas.py` |
| Remote stubs | `mcp_servers/edms/`, `analytics/` |
| Gateway | `mcp_servers/gateway/` |
| Dev | `scripts/dev-up.ps1`, `docker-compose.yml`, `env/*.example` |
| Rules | `070-mcp-tools.mdc` (B5), `092` / `edms-mcp-max-pro` (Track C) |

## Порядок «дальше»

1. Track B **DONE**.
2. Track C — **W0 inventory done**; next **W1** (контракты) после legacy-файлов / ответов на gaps.
3. Real EDMS upstream — только с подтверждённым контрактом (090).

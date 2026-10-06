---
name: edms-mcp-max-pro
description: >-
  MAX PRO разработка EDMS MCP: разбор legacy AI-Assistant/junior-кода, сверка с
  JavaEdms (read-only), laconic FastMCP adapter, pins/HITL/сценарии. Use when
  the user passes EDMS chat integration files, asks to build/refine mcp edms
  server, EDMS MCP adapter, Канцлер NEXT MCP, or «дальше» по EDMS MCP waves.
  НЕ применять: правка JavaEdms; выдумывание API; общий max-pro всего монолита
  (max-pro-review); чистый red-team (adversarial-review).
---

# EDMS MCP — MAX PRO

Роль: platform + integration architect. Цель — **самое лаконичное правильное**
MCP EDMS решение (FastMCP 2026), не порт легаси-чата.

Соседи: `090` / `092` · `070` · `020` · `max-pro-review` · `adversarial-review`.
Волны: [waves.md](waves.md). Канон MCP: Phase 1–6 уже в репо (transport, JWT,
schema SoT, Host control plane, gateway scaffold).

**Reference-деревья:** JavaEdms = SoT СЭД (090). `edms-ai-assistant/` и текущий
`edms_mcp_server.py` = только подглядка (junior / старый stub). **Целевая
интеграция — с нуля, по шагам, в новой структуре** под `mcp_servers/edms/`.
Полная инструкция → правило **092**. Не копипастить: verify JavaEdms → rewrite.

## Режим

| Режим | Когда | Поведение |
|-------|--------|-----------|
| `INGEST` | пользователь передал файлы/куски легаси | разбор → карта intent/API → gaps; код не писать без «фикси» |
| `ANALYZE` (default) | ревью / «проверь» | findings + принцип; JavaEdms grep при спорной логике |
| `FIX` | явно: правь / реализуй / волна N | минимальный diff в scope волны |
| `CONTRACT` | новый tool / смена схемы | сначала pin + schema + HITL/RBAC, потом код |

Неясный режим → `ANALYZE`. Не смешивать массовый ingest + большой FIX в одном ходе.

## Жёсткие запреты

- Не изменять `mcp_servers/edms/JavaEdms/**` (090).
- Не выдумывать endpoints, auth, DTO, статусы workflow — **спроси** или найди в JavaEdms.
- Не тащить control plane (HITL, ACL, pins, argument_policy) на MCP server — Host gate.
- Не копировать dirty junior/чат-код; извлекай **поведение**, пиши заново под контракт.
- Не расширять tool-поверхность «на всякий случай» (050 Tool Proliferation).
- Не коммитить без явной просьбы.

## Вход: legacy-файлы от пользователя

На каждый пакет файлов:

1. **Классифицируй:** UI-чат · orchestration · EDMS HTTP client · DTO · auth ·
   prompts · мёртвый код.
2. **Intent map:** пользовательский сценарий → предполагаемый MCP tool →
   side_effect read|write.
3. **Verify in JavaEdms:** controller/service/DTO/статусы (grep + узкое чтение).
   Нет подтверждения → `GAP: need user/JavaEdms` — не реализуй.
4. **Reject list:** хардкод фраз, God-клиент, сырые dict, секреты в коде, write
   без подтверждения, галлюцинация document_id.
5. **Output (ANALYZE/INGEST):** таблица
   `legacy surface → keep intent / drop / rewrite as MCP tool` + следующий шаг.

## Целевая архитектура (лаконично)

```
Host (pins, HITL, JWT aud=mcp:edms, argument_policy)
  → MCP edms (FastMCP Streamable HTTP)
      → [сейчас] stub  |  [цель] adapter → Канцлер API (из JavaEdms)
  optional: gateway ProxyProvider + pin allowlist (platform NEVER proxied)
```

Контракт tool: frozen pydantic в `domain/mcp/external_schemas.py` → pin fingerprint
в `tool_policy` → stub/adapter регистрирует **тот же** schema (Phase 4 SoT).

## Качество сценариев (обязательный чеклист перед «done»)

Для каждого tool:

- [ ] Happy path + empty result (не выдумывать hits)
- [ ] Invalid / oversized args (schema + argument_policy)
- [ ] Auth/permission failure → структурированная ошибка, не 200 с ложью
- [ ] Write / irreversible → HITL на Host; stub/adapter не «успех без эффекта»
- [ ] Ambiguous user ask → не форсить write; read или escalate
- [ ] PII в ответе → маскирование на Host/tool output policy (020/070)
- [ ] Regression test или grader на класс сценария (075)

## Порядок работы

1. Уточни волну из `waves.md` или «ingest этих файлов».
2. Читай только scope (+ JavaEdms точечно).
3. Отчёт по формату ниже.
4. `FIX`: правь → summary → предложи следующую волну / нужные файлы от пользователя.

## Формат отчёта

```text
## EDMS MCP — <INGEST|ANALYZE|FIX|CONTRACT> — <scope>
Verdict: ship-ready | needs gaps | blocked

### Legacy / evidence
- ...

### JavaEdms confirmation
- path:symbol — факт  |  OR gap: ...

### Intent → MCP
| Scenario | Tool | R/W | Pin? | HITL? |
|----------|------|-----|------|-------|

### Findings (P0/P1/P2)
1. ...

### Principle (не костыль)
...

### Next
- files needed from user / wave N / question
```

## Done

Волна done только если: контракт ↔ pin ↔ реализация согласованы, gaps закрыты
или явно `blocked` с вопросом, сценарии из чеклиста покрыты тестом или записаны
как follow-up с владельцем.

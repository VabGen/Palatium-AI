# Plan: `platform.read_attachment` + lazy OCR (Vision fallback)

**Status:** Phase A/B/C done (2026-10-12)  
**Priority:** rules 000/017/020/035/060/070/075/080 win over this doc.  
**Branch:** master

---

## Phase A — Reconnaissance summary

### LLM / Vision (reuse — do NOT create a new HTTP client)

| Piece | Location | Role |
|---|---|---|
| Agent LLM | `infrastructure/llm/litellm_adapter.py` → `LiteLLMAdapter` via `LLMPort` / `LLMClientFactory` | Chat completions for agents |
| **Image Vision OCR** | `infrastructure/parsing/image_ocr.py` → `GatewayImageOcrParser` | `litellm.acompletion` + `image_url` data-URL |
| **PDF Vision** | `infrastructure/parsing/pdf_vision.py` → `GatewayPdfVisionParser` | page raster → same gateway |
| **Tesseract** | `infrastructure/parsing/tesseract_ocr.py` (+ `pdf_ocr.py`) | local OCR |
| **Cascade** | `FallbackImageOcrParser` + `RoutedDocumentParser` in `parsing/factory.py` | Tesseract → Vision escalate already wired |
| Config | `core/config/attachments.py` | `image_ocr_backend=auto`, `image_ocr_model`, thresholds |

**Verdict:** Vision already exists as `DocumentParserPort` adapters on the LiteLLM gateway.  
**Do not** add `VisionPort` / new HTTP client. Lazy re-parse = call existing `DocumentParserPort.parse(...)`.

### Attachments domain (facts ≠ prompt assumptions)

| Prompt assumption | Reality in repo |
|---|---|
| Column `extracted_text` | **Absent.** Text = MinIO blob at `derived_text_key` (`AttachmentContent` JSON) |
| `extract_status` / `extracted_chars` / `ocr_applied` | **Absent** from ORM + migrations |
| `DocumentExtractor` | **No such type.** Port = `DocumentParserPort` |
| MinIO at `infrastructure/storage/minio` | Actual: `infrastructure/blob/minio_adapter.py` via `BlobStorePort` |
| `AttachmentReadPort` | **Does not exist yet** |

**Schema (`palatium_ai.attachments`):**  
`user_id`, `thread_id`, `filename`, `mime_type`, `size_bytes`, `blob_key`, `mode`, `status`, `page_count`, `derived_text_key`, `rejection_reason`, `error`, `project_id`, `contains_pii`, `expires_at`, timestamps.  
FORCE RLS by `user_id` ↔ `palatium.user_id`.

**Derived content:** `domain/attachments/content.py` → `AttachmentContent` (`pages`, `safe_text`, `scan`, `truncated`, `contains_pii`).  
Empty `safe_text` → `is_prompt_eligible=False` → `_reviewed_body` raises `AttachmentNotUsableError` (turn can fail / no fence).

### Repository / service / pipeline

- Port: `domain/ports/attachments.py` → `AttachmentRepositoryPort` (`get`/`get_many`/`save` always require `user_id`).
- Adapter: `infrastructure/database/attachment_repository.py`.
- Use-case: `application/services/attachment_service.py` — `build_turn_context`, `complete_upload`, index HITL.
- Pipeline: `application/services/attachment_pipeline.py` — sniff → AV → parse (OCR/Vision) → PII/injection → `status=ready` + write derived blob.
- Errors: `AttachmentNotFoundError` already unified (no enumeration). `AttachmentUploadTooLargeError` exists; ceiling already **50 MiB** (`ATTACHMENTS_MAX_SIZE_BYTES`).
- **No** `POST …/reingest` yet (router has init/complete/upload/index/restore/analysis/delete).

### Context / Researcher

- `build_turn_context` → `_fence_for_turn` → fenced `<<<UNTRUSTED_TOOL_OUTPUT …>>>` via `wrap_untrusted_tool_output`.
- No `[!CAUTION]` today for empty OCR.
- Researcher `allowed_tools`: search_knowledge/memory/graph/skill/web + EDMS/analytics — **no** read_attachment.
- Prompt says OCR already ran; if fence empty → «no usable text» — does **not** tell agent to call a tool.

### MCP / RBAC / DI

- Pins: `domain/mcp/tool_policy.py` `_PLATFORM_SIDE_EFFECTS` + schemas in `platform_schemas.py`.
- Handler: `infrastructure/mcp/platform_tool_handler.py` (ingest/search_*/memory/graph/skill/web).
- Bootstrap: `application/bootstrap.py` wires `PlatformToolHandler` **without** attachment deps today.
- Wiring: `application/wiring.py` builds `AttachmentService` + `DocumentParserPort` + `BlobStorePort`.
- Actor: `actor_user_id` from Researcher → MCP call; tools read `arguments["user_id"]` (same pattern as search_memory).
- **070:** new tool = update closed catalog in rule + pin + schema + agent allow-list (explicit discussion).

### Observability

- Existing: `palatium_attachment_parse_total{extraction_source,media_kind}`.
- Proposed new: `palatium_attachment_read_total{…}` (must register in `core/observability/metrics.py` — 040).

---

## Open decisions (need your «ок» / answers)

1. **Cache storage:** keep write-through in **derived blob** (`AttachmentContent`), optionally add additive fields `extraction_source` / `ocr_engine` on the content envelope — **no** Alembic columns `extracted_text` / `extract_status` / `ocr_applied` unless you insist. DoD SQL would become blob/content inspection (or we add a thin migration if you want SQL columns).
2. **No new VisionPort** — reuse `DocumentParserPort` (already Tesseract→Vision). Confirm.
3. **Pin side_effect:** tool is agent-facing **read**; internal cache write to owner's derived blob. Propose `side_effect="read"`, `requires_hitl=False`, `risk_tier="low"` (same class as search_memory). Confirm (write-through is not user-initiated knowledge ingest).
4. **070 catalog update** for `read_attachment` — confirm (rule + pin required).
5. **Empty fence behavior:** today empty `safe_text` → `AttachmentNotUsableError`. Propose: allow a **notice fence** with `[!CAUTION]` + attachment_id so Researcher can call `read_attachment` instead of failing the turn / minting HITL.

---

## Phase B — Task plan + commits

Adapted to repo facts (DocumentParserPort, derived blob, existing errors).

### Commit 1 — `feat(attachments): domain AttachmentRead types + port`

- `AttachmentReadRequest` / `AttachmentReadResult` (offset, max_chars, truncated, ocr_applied, ocr_cached, ocr_engine, notice).
- `AttachmentReadPort` Protocol (or method on existing service port if cleaner — prefer thin port used by MCP).
- Errors: reuse `AttachmentNotFoundError`; add `AttachmentTooLargeError` only if distinct from upload cap (else reuse `AttachmentUploadTooLargeError` / size check against `AttachmentLimits.max_size_bytes`).
- Do **not** invent `OcrEngineUnavailableError` as crash path — parser cascade already handles; surface as `notice` when both fail.

### Commit 2 — `feat(attachments): AttachmentReadService RBAC + lazy parse + cache`

- Owner check via `repository.get(id, user_id=…)` → missing ⇒ `AttachmentNotFoundError`.
- Cached path: derived `safe_text` non-empty and not `force_ocr` → slice.
- Lazy path: `blob_store.read_bytes(blob_key)` → `document_parser.parse` (Tesseract→Vision inside) → rewrite `AttachmentContent` + `repository.save` metadata (`page_count`, `contains_pii` as today).
- Ceiling: `size_bytes` / blob stat vs `max_size_bytes` (50 MiB).
- Both engines fail / empty text → result with `notice`, no exception to agent.
- Metrics/logs: `attachment_read.*`, `palatium_attachment_read_total`.

### Commit 3 — `feat(attachments): persist extraction_source on AttachmentContent` (additive)

- Optional fields on `AttachmentContent` with defaults (backward-compatible JSON).
- Update pipeline admit path to stamp `extraction_source` from `ParsedDocument`.
- No Alembic unless decision #1 chooses SQL columns.

### Commit 4 — `feat(mcp): platform.read_attachment pin + handler`

- Frozen I/O in `platform_schemas.py`.
- Pin in `tool_policy.py`; update `.cursor/rules/070-mcp-tools.mdc` catalog.
- `PlatformToolHandler` branch; inject `AttachmentReadService`.
- Fence response `<<<ATTACHMENT:name>>>…<<<END_ATTACHMENT>>>` (or reuse existing untrusted fence helper for consistency with 020 — prefer existing wrap if ATTACHMENT format conflicts with injection policy; ask if strict ATTACHMENT markers required).
- Researcher `allowed_tools` += `mcp:platform.read_attachment`.

### Commit 5 — `feat(researcher): prompt guidance for read_attachment`

- If context says text missing / scan without OCR → call tool; do **not** mint HITL / ask re-upload.

### Commit 6 — `feat(attachments): CAUTION notice in build_turn_context`

- `status in {ready,indexed}` + empty/missing usable text → fenced notice with `[!CAUTION]` + `attachment_id` (contract additive only).

### Commit 7 — `feat(api): POST /api/attachments/{id}/reingest`

- Owner-only: re-run pipeline on existing blob (reset derived, `complete`-like path).
- 202 + body; other user → 404 (unified); unauthenticated/wrong → 403/404 per existing router patterns.

### Commit 8 — `feat(bootstrap): wire AttachmentReadService into PlatformToolHandler`

- DI in `wiring.py` / `bootstrap.py`.

### Commit 9 — `test(attachments): unit+integration for read / RBAC / OCR / reingest`

- Cases from DoD: RBAC, cached, lazy, Vision fallback, both unavailable → notice, size ceiling, MCPToolResult shape, reingest 202/403/404.

### Commit 10 — `docs(plan): mark attachment read-tool task done`

Gates after each commit: `ruff`, `mypy`, targeted `pytest`.

---

## Out of scope (explicit)

- New LiteLLM/Vision HTTP client  
- Qdrant  
- Auto re-ingest of all historical scans  
- Editing JavaEdms / widening beyond this tool  
- Changing `attachment_context` contract except additive notice fields  

---

## Definition of Done (adapted)

- [x] `platform.read_attachment` in platform list_tools / pins  
- [x] Foreign `user_id` → `AttachmentNotFoundError`  
- [x] First scan read → parse + write-through derived blob; second → cached  
- [x] Tesseract unavailable → Vision via existing parser; `ocr_engine` reflects source  
- [x] Both unavailable → `notice`, no crash  
- [x] > max_size_bytes → typed too-large error  
- [x] Researcher uses tool instead of HITL re-upload  
- [x] CAUTION notice in turn context for empty text  
- [x] `POST …/reingest` 202 for owner  
- [x] Logs + metrics registered in 040 registry  
- [x] Unit tests green for new paths (ruff clean on touched files)  
- [x] **No new Vision HTTP client**

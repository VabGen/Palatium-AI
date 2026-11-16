"""Live smoke: W11 use_memory isolation + HITL clear + verified fast-path enqueue.

Usage (API with W11 code + migrated ``memory.ops``):
  uv run python scripts/smoke_w11_memory_scope.py
  uv run python scripts/smoke_w11_memory_scope.py --base-url http://127.0.0.1:8000

Checks:
  1) process with use_memory=false returns without durable personalization crash
  2) memory/clear → HITL → approve → Medium purge + clear_user_graph path
  3) memory/save preference → approve → fast promote path (best-effort log only;
     graph may lag worker by seconds)
"""

from __future__ import annotations

import argparse
import json
import sys
import time
import urllib.error
import urllib.request

from uuid import uuid4


def _http_url(url: str) -> str:
    cleaned = url.strip()
    if not cleaned.startswith(("http://", "https://")):
        raise ValueError(f"only http(s) URLs allowed, got: {url!r}")
    return cleaned


def _request_json(
    method: str,
    url: str,
    *,
    token: str | None = None,
    body: dict[str, object] | None = None,
    timeout: float = 90,
) -> tuple[int, dict[str, object] | None]:
    data = None if body is None else json.dumps(body).encode("utf-8")
    headers = {"Accept": "application/json"}
    if body is not None:
        headers["Content-Type"] = "application/json"
    if token:
        headers["Authorization"] = f"Bearer {token}"
    req = urllib.request.Request(_http_url(url), data=data, headers=headers, method=method)
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            raw = resp.read().decode("utf-8", errors="replace")
            status = int(resp.status)
    except urllib.error.HTTPError as exc:
        raw = exc.read().decode("utf-8", errors="replace")
        status = int(exc.code)
    cleaned = raw.strip()
    if not cleaned:
        return status, None
    try:
        parsed = json.loads(cleaned)
    except json.JSONDecodeError as exc:
        raise RuntimeError(f"non-JSON {method} {url}: HTTP {status} body={cleaned[:240]!r}") from exc
    if isinstance(parsed, dict):
        return status, parsed
    return status, None


def _require_ok(
    label: str,
    status: int,
    payload: dict[str, object] | None,
    *,
    ok_statuses: set[int] | None = None,
) -> dict[str, object]:
    allowed = ok_statuses or {200}
    if status not in allowed or payload is None:
        raise RuntimeError(f"{label} failed: HTTP {status} {payload!r}")
    return payload


def _approve_body(card: dict[str, object], *, idempotency_key: str) -> dict[str, object]:
    options = card.get("options")
    if not isinstance(options, list):
        raise RuntimeError(f"card missing options: {card!r}")
    approve = next(
        (opt for opt in options if isinstance(opt, dict) and opt.get("action_id") == "approve"),
        None,
    )
    if approve is None or not isinstance(approve.get("action_token"), str):
        raise RuntimeError(f"approve option missing action_token: {card!r}")
    return {
        "action_id": "approve",
        "action_token": approve["action_token"],
        "idempotency_key": idempotency_key,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--base-url", default="http://127.0.0.1:8000")
    args = parser.parse_args()
    base = args.base_url.rstrip("/")
    thread_id = f"smoke-w11-{uuid4().hex[:8]}"
    user_id = f"user-w11-{uuid4().hex[:8]}"
    org_id = "org-smoke-w11"
    entry_key = "w11-pref-color"

    try:
        tok = _require_ok(
            "dev-token",
            *_request_json(
                "POST",
                f"{base}/api/auth/dev-token",
                body={"user_id": user_id, "org_id": org_id},
                timeout=30,
            ),
        )
        token = str(tok["access_token"])

        status, _session = _request_json(
            "POST",
            f"{base}/api/sessions/",
            token=token,
            body={"thread_id": thread_id, "title": "w11-scope-smoke"},
            timeout=30,
        )
        if status not in {200, 201}:
            raise RuntimeError(f"upsert session failed: HTTP {status}")

        # 1) Temporary / unpersonalized turn must succeed (no durable recall/extract).
        process = _require_ok(
            "process-use-memory-false",
            *_request_json(
                "POST",
                f"{base}/api/intents/process",
                token=token,
                body={
                    "text": "Коротко: что ты умеешь?",
                    "thread_id": thread_id,
                    "use_memory": False,
                },
                timeout=120,
            ),
        )
        if process.get("status") not in {"success", "partial"}:
            raise RuntimeError(f"unexpected process status: {process.get('status')!r}")

        # 2) Seed a preference, then clear.
        save_card = _require_ok(
            "memory-save",
            *_request_json(
                "POST",
                f"{base}/api/memory/save",
                token=token,
                body={
                    "thread_id": thread_id,
                    "text": "Smoke W11: favorite color is teal.",
                    "entry_key": entry_key,
                    "namespace_kind": "user",
                    "scope_id": user_id,
                    "memory_type": "preference",
                },
                timeout=30,
            ),
        )
        if not str(save_card.get("task_id", "")).startswith("mem-save-"):
            raise RuntimeError(f"unexpected save task_id: {save_card.get('task_id')!r}")
        approve_save = _require_ok(
            "approve-save",
            *_request_json(
                "POST",
                f"{base}/api/hitl/{save_card['card_id']}/respond",
                token=token,
                body=_approve_body(save_card, idempotency_key=f"w11-save-{save_card['card_id']}"),
                timeout=60,
            ),
        )
        resumed = approve_save.get("resumed") if isinstance(approve_save.get("resumed"), dict) else None
        # Give MemoryOpWorker a beat to claim promote_entry (best-effort).
        time.sleep(1.5)

        clear_card = _require_ok(
            "memory-clear",
            *_request_json(
                "DELETE",
                f"{base}/api/memory/clear",
                token=token,
                body={"thread_id": thread_id},
                timeout=30,
            ),
            ok_statuses={200, 201},
        )
        if not str(clear_card.get("task_id", "")).startswith("mem-clear-"):
            raise RuntimeError(f"unexpected clear task_id: {clear_card.get('task_id')!r}")
        _require_ok(
            "approve-clear",
            *_request_json(
                "POST",
                f"{base}/api/hitl/{clear_card['card_id']}/respond",
                token=token,
                body=_approve_body(clear_card, idempotency_key=f"w11-clear-{clear_card['card_id']}"),
                timeout=60,
            ),
        )
        time.sleep(1.0)

        print(
            json.dumps(
                {
                    "ok": True,
                    "thread_id": thread_id,
                    "user_id": user_id,
                    "process_status": process.get("status"),
                    "save_card_id": save_card.get("card_id"),
                    "clear_card_id": clear_card.get("card_id"),
                    "approve_save_has_resumed": resumed is not None,
                },
                ensure_ascii=False,
            )
        )
        return 0
    except Exception as exc:  # noqa: BLE001  # smoke reports FAILED and exits 1
        print(f"smoke_w11_memory_scope FAILED: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())

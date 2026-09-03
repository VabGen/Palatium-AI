"""Live smoke: off-graph memory HITL save → approve → forget → approve.

Usage (API up, auth/dev-token available):
  poetry run python scripts/smoke_memory_hitl.py
  poetry run python scripts/smoke_memory_hitl.py --base-url http://127.0.0.1:8000

Flow:
  1) POST /api/auth/dev-token
  2) POST /api/sessions
  3) POST /api/memory/save → HITL card
  4) POST /api/hitl/{id}/respond approve
  5) POST /api/memory/forget → HITL card
  6) POST /api/hitl/{id}/respond approve
"""

from __future__ import annotations

import argparse
import json
import sys
import urllib.error
import urllib.request

from uuid import uuid4


def _http_url(url: str) -> str:
    cleaned = url.strip()
    if not (cleaned.startswith("http://") or cleaned.startswith("https://")):
        raise ValueError(f"only http(s) URLs allowed, got: {url!r}")
    return cleaned


def _request_json(
    method: str,
    url: str,
    *,
    token: str | None = None,
    body: dict[str, object] | None = None,
    timeout: float = 60,
) -> tuple[int, dict[str, object] | None]:
    data = None if body is None else json.dumps(body).encode("utf-8")
    headers = {"Accept": "application/json"}
    if body is not None:
        headers["Content-Type"] = "application/json"
    if token:
        headers["Authorization"] = f"Bearer {token}"
    req = urllib.request.Request(  # noqa: S310
        _http_url(url),
        data=data,
        headers=headers,
        method=method,
    )
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:  # noqa: S310
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
        raise RuntimeError(f"non-JSON response for {method} {url}: HTTP {status} body={cleaned[:240]!r}") from exc
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
    """Run memory save/forget HITL smoke against a live API."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--base-url", default="http://127.0.0.1:8000")
    args = parser.parse_args()
    base = args.base_url.rstrip("/")
    thread_id = f"smoke-mem-{uuid4().hex[:8]}"
    user_id = f"user-mem-{uuid4().hex[:8]}"
    org_id = "org-smoke"
    entry_key = "smoke-pref-lang"

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
            body={"thread_id": thread_id, "title": "memory-hitl-smoke"},
            timeout=30,
        )
        if status not in {200, 201}:
            raise RuntimeError(f"upsert session failed: HTTP {status}")

        save_card = _require_ok(
            "memory-save",
            *_request_json(
                "POST",
                f"{base}/api/memory/save",
                token=token,
                body={
                    "thread_id": thread_id,
                    "text": "Smoke test: user prefers Russian responses.",
                    "entry_key": entry_key,
                    "namespace_kind": "user",
                    "scope_id": user_id,
                    "memory_type": "preference",
                },
                timeout=30,
            ),
        )
        task_id = str(save_card.get("task_id", ""))
        if not task_id.startswith("mem-save-"):
            raise RuntimeError(f"unexpected save task_id: {task_id!r}")

        _require_ok(
            "approve-save",
            *_request_json(
                "POST",
                f"{base}/api/hitl/{save_card['card_id']}/respond",
                token=token,
                body=_approve_body(save_card, idempotency_key=f"smoke-save-{save_card['card_id']}"),
                timeout=60,
            ),
        )

        forget_card = _require_ok(
            "memory-forget",
            *_request_json(
                "POST",
                f"{base}/api/memory/forget",
                token=token,
                body={
                    "thread_id": thread_id,
                    "entry_key": entry_key,
                    "namespace_kind": "user",
                    "scope_id": user_id,
                },
                timeout=30,
            ),
        )
        forget_task = str(forget_card.get("task_id", ""))
        if not forget_task.startswith("mem-forget-"):
            raise RuntimeError(f"unexpected forget task_id: {forget_task!r}")

        _require_ok(
            "approve-forget",
            *_request_json(
                "POST",
                f"{base}/api/hitl/{forget_card['card_id']}/respond",
                token=token,
                body=_approve_body(forget_card, idempotency_key=f"smoke-forget-{forget_card['card_id']}"),
                timeout=60,
            ),
        )

        print(
            json.dumps(
                {
                    "ok": True,
                    "thread_id": thread_id,
                    "save_card_id": save_card.get("card_id"),
                    "forget_card_id": forget_card.get("card_id"),
                },
                ensure_ascii=False,
            )
        )
        return 0
    except Exception as exc:
        print(f"smoke_memory_hitl FAILED: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())

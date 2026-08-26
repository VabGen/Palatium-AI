"""Deterministic write-HITL + IdP step-up smoke (no LLM tool choice).

Usage (API in development with HITL_STEP_UP_REQUIRED=true and idp_acr):
  poetry run python scripts/smoke_hitl_write_step_up.py
  poetry run python scripts/smoke_hitl_write_step_up.py --base-url http://127.0.0.1:8000

Flow:
  1) POST /api/auth/dev-token
  2) POST /api/sessions (claim thread)
  3) POST /api/hitl/dev/mint-tool-approval (archive_document write card)
  4) POST /api/hitl/{id}/step-up-challenge
  5) GET  /api/auth/dev-hitl-step-up (JSON assertion) or use challenge.assertion for hmac_stub
  6) POST /api/hitl/{id}/respond with step_up_assertion
"""

from __future__ import annotations

import argparse
import json
import sys
import urllib.error
import urllib.parse
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
    accept: str = "application/json",
    timeout: float = 60,
) -> tuple[int, dict[str, object] | None]:
    data = None if body is None else json.dumps(body).encode("utf-8")
    headers = {"Accept": accept}
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
        raise RuntimeError(
            f"non-JSON response for {method} {url}: HTTP {status} body={cleaned[:240]!r}"
        ) from exc
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


def _mint_assertion(
    base: str,
    *,
    card_id: str,
    user_id: str,
    challenge: dict[str, object],
) -> str | None:
    if not challenge.get("required"):
        return None
    if isinstance(challenge.get("assertion"), str) and challenge["assertion"]:
        return str(challenge["assertion"])
    query = urllib.parse.urlencode(
        {
            "card_id": card_id,
            "subject": user_id,
            "challenge": str(challenge.get("challenge") or ""),
            "required_acr": str(challenge.get("required_acr") or "urn:palatium:acr:step-up"),
            "card_claim": str(challenge.get("card_claim") or "hitl_card_id"),
            "method": str(challenge.get("method") or "idp_acr"),
        }
    )
    status, stub = _request_json("GET", f"{base}/api/auth/dev-hitl-step-up?{query}", timeout=30)
    if status != 200 or not stub or not isinstance(stub.get("assertion"), str):
        raise RuntimeError(
            f"dev-hitl-step-up failed: HTTP {status} {stub!r} "
            "(set HITL_STEP_UP_REQUIRED=true and HITL_STEP_UP_METHOD=idp_acr for IdP path)"
        )
    return str(stub["assertion"])


def main() -> int:
    """Run deterministic write-HITL + step-up smoke against a live API."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--base-url", default="http://127.0.0.1:8000")
    args = parser.parse_args()
    base = args.base_url.rstrip("/")
    thread_id = f"smoke-write-{uuid4().hex[:8]}"
    user_id = f"user-write-{uuid4().hex[:8]}"
    org_id = "org-smoke"

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
        if not token:
            raise RuntimeError("dev-token missing access_token")

        status, _session = _request_json(
            "POST",
            f"{base}/api/sessions/",
            token=token,
            body={"thread_id": thread_id, "title": "write-hitl-smoke"},
            timeout=30,
        )
        if status not in {200, 201}:
            raise RuntimeError(f"upsert session failed: HTTP {status}")

        card = _require_ok(
            "mint-tool-approval",
            *_request_json(
                "POST",
                f"{base}/api/hitl/dev/mint-tool-approval",
                token=token,
                body={
                    "thread_id": thread_id,
                    "server_name": "edms",
                    "tool_name": "archive_document",
                    "side_effect": "write",
                    "risk_score": 0.85,
                    "argument_preview": "document_id=DOC-SMOKE-001",
                },
                timeout=30,
            ),
        )
        card_id = str(card.get("card_id") or "")
        if not card_id:
            raise RuntimeError("minted card missing card_id")

        challenge = _require_ok(
            "step-up-challenge",
            *_request_json(
                "POST",
                f"{base}/api/hitl/{card_id}/step-up-challenge",
                token=token,
                body={},
                timeout=30,
            ),
        )
        assertion = _mint_assertion(base, card_id=card_id, user_id=user_id, challenge=challenge)

        live = _require_ok(
            "GET hitl card",
            *_request_json("GET", f"{base}/api/hitl/{card_id}", token=token, timeout=30),
        )
        options = live.get("options")
        if not isinstance(options, list):
            raise RuntimeError("live card missing options")
        approve = next(
            (
                opt
                for opt in options
                if isinstance(opt, dict) and opt.get("action_id") in {"approve", "allow"}
            ),
            None,
        )
        if not isinstance(approve, dict):
            raise RuntimeError("no approve option")
        respond_body: dict[str, object] = {
            "action_id": str(approve["action_id"]),
            "action_token": str(approve["action_token"]),
            "idempotency_key": f"smoke-write-{uuid4().hex}",
        }
        if assertion:
            respond_body["step_up_assertion"] = assertion

        respond = _require_ok(
            "respond",
            *_request_json(
                "POST",
                f"{base}/api/hitl/{card_id}/respond",
                token=token,
                body=respond_body,
                timeout=60,
            ),
        )
        resolve = respond.get("resolve")
        card_view = resolve.get("card") if isinstance(resolve, dict) else None
        final_status = card_view.get("status") if isinstance(card_view, dict) else None
        summary = {
            "thread_id": thread_id,
            "card_id": card_id,
            "step_up_required": challenge.get("required"),
            "step_up_method": challenge.get("method"),
            "final_status": final_status,
        }
        print(json.dumps(summary, ensure_ascii=False, indent=2))
        if final_status != "resolved":
            print("FAIL: card not resolved", file=sys.stderr)
            return 1
        print("smoke_hitl_write_step_up: ok")
        return 0
    except (RuntimeError, ValueError, urllib.error.URLError, json.JSONDecodeError, TypeError) as exc:
        print(f"FAIL: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())

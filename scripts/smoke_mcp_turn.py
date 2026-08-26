"""Smoke: live /api/intents/process that should hit EDMS MCP stub.

Usage:
  poetry run python scripts/smoke_mcp_turn.py
  poetry run python scripts/smoke_mcp_turn.py --mode archive
  poetry run python scripts/smoke_mcp_turn.py --base-url http://127.0.0.1:8000

Expects MCP stubs with Bearer (scripts/dev-up.ps1 -SkipApi) and a running API.
Checks session mcp-tool-calls for edms.search_documents when the path succeeds,
or documents fail-closed (no tool row) when MCP is unreachable from the API process.

If process returns mcp_tool_approval HITL cards (write/unknown tools), the smoke
completes step-up-challenge → respond(approve) and re-checks tool calls.
`--mode archive` prefers the write HITL interrupt path (edms.archive_document).
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
    url: str,
    *,
    method: str = "GET",
    token: str | None = None,
    payload: dict[str, object] | None = None,
    timeout: float = 180.0,
) -> tuple[int, dict[str, object] | list[object] | None]:
    headers = {"Content-Type": "application/json"}
    if token:
        headers["Authorization"] = f"Bearer {token}"
    body = None if payload is None else json.dumps(payload).encode("utf-8")
    req = urllib.request.Request(  # noqa: S310
        _http_url(url),
        data=body,
        headers=headers,
        method=method,
    )
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:  # noqa: S310
            raw = resp.read().decode("utf-8")
            status = int(resp.status)
    except urllib.error.HTTPError as exc:
        raw = exc.read().decode("utf-8", errors="replace")
        status = int(exc.code)
    if not raw:
        return status, None
    data = json.loads(raw)
    if isinstance(data, (dict, list)):
        return status, data
    return status, None


def _approve_mcp_hitl(  # noqa: C901
    *,
    base: str,
    token: str,
    card: dict[str, object],
) -> dict[str, object]:
    """GET live tokens → optional step-up → respond(approve)."""
    card_id = str(card.get("card_id") or "")
    if not card_id:
        raise RuntimeError("mcp_tool_approval card missing card_id")

    status, live = _request_json(f"{base}/api/hitl/{card_id}", token=token, timeout=30)
    if status != 200 or not isinstance(live, dict):
        raise RuntimeError(f"GET hitl card failed: HTTP {status}")
    options = live.get("options")
    if not isinstance(options, list) or not options:
        raise RuntimeError("live HITL card has no options")
    approve = next(
        (opt for opt in options if isinstance(opt, dict) and opt.get("action_id") in {"approve", "allow"}),
        None,
    )
    if not isinstance(approve, dict):
        raise RuntimeError("no approve/allow option on MCP HITL card")
    action_token = str(approve.get("action_token") or "")
    action_id = str(approve.get("action_id") or "")
    if not action_token or not action_id:
        raise RuntimeError("approve option missing action_token")

    step_up_assertion: str | None = None
    risk_raw = live.get("risk_score")
    risk = float(risk_raw) if isinstance(risk_raw, (int, float, str)) else 0.0
    if risk >= 0.7:
        status, challenge = _request_json(
            f"{base}/api/hitl/{card_id}/step-up-challenge",
            method="POST",
            token=token,
            payload={},
            timeout=30,
        )
        if status != 200 or not isinstance(challenge, dict):
            raise RuntimeError(f"step-up-challenge failed: HTTP {status}")
        if challenge.get("required"):
            assertion = challenge.get("assertion")
            if not isinstance(assertion, str) or not assertion:
                raise RuntimeError("step-up required but assertion missing")
            step_up_assertion = assertion

    body: dict[str, object] = {
        "action_id": action_id,
        "action_token": action_token,
        "idempotency_key": f"smoke-mcp-{uuid4().hex}",
    }
    if step_up_assertion:
        body["step_up_assertion"] = step_up_assertion
    status, respond = _request_json(
        f"{base}/api/hitl/{card_id}/respond",
        method="POST",
        token=token,
        payload=body,
        timeout=300,
    )
    if status != 200 or not isinstance(respond, dict):
        raise RuntimeError(f"HITL respond failed: HTTP {status} {respond!r}")
    return respond


def main() -> int:  # noqa: C901
    """Smoke: live /api/intents/process that should hit EDMS MCP stub."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--base-url", default="http://127.0.0.1:8000")
    parser.add_argument(
        "--mode",
        choices=("search", "archive"),
        default="search",
        help="search = read path; archive = write tool (expects mcp_tool_approval HITL).",
    )
    args = parser.parse_args()
    base = args.base_url.rstrip("/")
    thread_id = f"smoke-mcp-{uuid4().hex[:8]}"
    user_id = f"user-mcp-{uuid4().hex[:8]}"

    try:
        status, token_body = _request_json(
            f"{base}/api/auth/dev-token",
            method="POST",
            payload={"user_id": user_id},
            timeout=30,
        )
        if status != 200 or not isinstance(token_body, dict):
            raise RuntimeError(f"dev-token failed: HTTP {status} {token_body!r}")
        token = token_body.get("access_token")
        if not isinstance(token, str) or not token:
            raise RuntimeError("dev-token missing access_token")

        if args.mode == "archive":
            text = "Архивируй в СЭД документ с идентификатором DOC-SMOKE-001"
            expect_tool = "archive_document"
        else:
            text = "Найди в СЭД документы по запросу договор поставки"
            expect_tool = "search_documents"
        status, process_body = _request_json(
            f"{base}/api/intents/process",
            method="POST",
            token=token,
            payload={"text": text, "thread_id": thread_id},
        )
        if status != 200 or not isinstance(process_body, dict):
            raise RuntimeError(f"process failed: HTTP {status} {process_body!r}")

        hitl_cards = process_body.get("hitl_cards")
        mcp_cards: list[dict[str, object]] = []
        if isinstance(hitl_cards, list):
            mcp_cards = [
                card for card in hitl_cards if isinstance(card, dict) and card.get("purpose") == "mcp_tool_approval"
            ]
        hitl_resume: dict[str, object] | None = None
        if mcp_cards:
            hitl_resume = _approve_mcp_hitl(base=base, token=token, card=mcp_cards[0])
            print("ok: mcp_tool_approval step-up/respond completed", flush=True)

        status, calls_body = _request_json(
            f"{base}/api/sessions/{thread_id}/mcp-tool-calls?limit=20",
            token=token,
            timeout=30,
        )
        if status != 200 or not isinstance(calls_body, dict):
            raise RuntimeError(f"mcp-tool-calls failed: HTTP {status} {calls_body!r}")
        items = calls_body.get("items")
        if not isinstance(items, list):
            raise RuntimeError("mcp-tool-calls missing items list")

        edms_calls = [
            item
            for item in items
            if isinstance(item, dict) and item.get("server_name") == "edms" and item.get("tool_name") == expect_tool
        ]
        hitl_status = None
        if hitl_resume is not None:
            resolve = hitl_resume.get("resolve")
            if isinstance(resolve, dict):
                card_view = resolve.get("card")
                if isinstance(card_view, dict):
                    hitl_status = card_view.get("status")
        summary = {
            "mode": args.mode,
            "thread_id": thread_id,
            "process_status": process_body.get("status"),
            "requires_review": process_body.get("requires_review"),
            "mcp_hitl_cards": len(mcp_cards),
            "hitl_resolved": hitl_status,
            "mcp_tool_call_count": len(items),
            "edms_target_calls": len(edms_calls),
            "expect_tool": expect_tool,
        }
        print(json.dumps(summary, ensure_ascii=False, indent=2))

        if args.mode == "archive":
            if mcp_cards and hitl_status == "resolved":
                print("smoke_mcp_turn: write HITL path exercised (mcp_tool_approval resolved)")
                return 0
            if edms_calls:
                print("smoke_mcp_turn: archive tool recorded (interrupt may have been skipped)")
                return 0
            print(
                "smoke_mcp_turn: archive mode — no mcp_tool_approval / archive calls "
                "(LLM may have chosen search; re-run or check Researcher plan)",
                file=sys.stderr,
            )
            return 1

        if edms_calls:
            print("smoke_mcp_turn: MCP path exercised (edms.search_documents recorded)")
            return 0

        # Fail-closed without inventing tool rows is acceptable when API→MCP auth is misaligned.
        print(
            "smoke_mcp_turn: no edms tool calls recorded (check API process MCP_AUTH_TOKEN matches stubs)",
            file=sys.stderr,
        )
        return 1
    except (RuntimeError, ValueError, urllib.error.URLError, json.JSONDecodeError, TypeError) as exc:
        print(f"FAIL: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())

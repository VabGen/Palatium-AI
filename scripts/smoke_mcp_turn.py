"""Smoke: live /api/intents/process that should hit EDMS MCP stub.

Usage:
  uv run python scripts/smoke_mcp_turn.py
  uv run python scripts/smoke_mcp_turn.py --mode archive
  uv run python scripts/smoke_mcp_turn.py --base-url http://127.0.0.1:8000

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
    if not cleaned.startswith(("http://", "https://")):
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


def _live_card(base: str, card_id: str, token: str) -> dict[str, object]:
    """The served card view, which carries the fresh action tokens."""
    status, live = _request_json(f"{base}/api/hitl/{card_id}", token=token, timeout=30)
    if status != 200 or not isinstance(live, dict):
        raise RuntimeError(f"GET hitl card failed: HTTP {status}")
    return live


def _approve_option(live: dict[str, object]) -> tuple[str, str]:
    """The card's ``approve``/``allow`` option as ``(action_token, action_id)``."""
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
    return action_token, action_id


def _mcp_step_up_assertion(base: str, card_id: str, token: str, live: dict[str, object]) -> str | None:
    """Assertion a high-risk card demands, or ``None`` when no step-up is required."""
    risk_raw = live.get("risk_score")
    risk = float(risk_raw) if isinstance(risk_raw, (int, float, str)) else 0.0
    if risk < 0.7:
        return None
    status, challenge = _request_json(
        f"{base}/api/hitl/{card_id}/step-up-challenge",
        method="POST",
        token=token,
        payload={},
        timeout=30,
    )
    if status != 200 or not isinstance(challenge, dict):
        raise RuntimeError(f"step-up-challenge failed: HTTP {status}")
    if not challenge.get("required"):
        return None
    assertion = challenge.get("assertion")
    if not isinstance(assertion, str) or not assertion:
        raise RuntimeError("step-up required but assertion missing")
    return assertion


def _approve_mcp_hitl(
    *,
    base: str,
    token: str,
    card: dict[str, object],
) -> dict[str, object]:
    """GET live tokens → optional step-up → respond(approve)."""
    card_id = str(card.get("card_id") or "")
    if not card_id:
        raise RuntimeError("mcp_tool_approval card missing card_id")

    live = _live_card(base, card_id, token)
    action_token, action_id = _approve_option(live)
    step_up_assertion = _mcp_step_up_assertion(base, card_id, token, live)

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


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--base-url", default="http://127.0.0.1:8000")
    parser.add_argument(
        "--mode",
        choices=("search", "archive"),
        default="search",
        help="search = read path; archive = write tool (expects mcp_tool_approval HITL).",
    )
    return parser


def _dev_token(base: str, user_id: str) -> str:
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
    return token


def _mode_prompt(mode: str) -> tuple[str, str]:
    """The prompt to send and the EDMS tool the run should produce, per mode."""
    if mode == "archive":
        return "Архивируй в СЭД документ с идентификатором DOC-SMOKE-001", "archive_document"
    return "Найди в СЭД документы по запросу договор поставки", "search_documents"


def _mcp_cards(process_body: dict[str, object]) -> list[dict[str, object]]:
    """The ``mcp_tool_approval`` cards the turn returned, in card order."""
    hitl_cards = process_body.get("hitl_cards")
    if not isinstance(hitl_cards, list):
        return []
    return [card for card in hitl_cards if isinstance(card, dict) and card.get("purpose") == "mcp_tool_approval"]


def _session_tool_calls(base: str, thread_id: str, token: str) -> list[object]:
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
    return items


def _edms_calls(items: list[object], expect_tool: str) -> list[object]:
    """Recorded calls that belong to the expected EDMS tool."""
    return [
        item
        for item in items
        if isinstance(item, dict) and item.get("server_name") == "edms" and item.get("tool_name") == expect_tool
    ]


def _hitl_status(hitl_resume: dict[str, object] | None) -> object:
    """Status of the resolved card, dug out of the respond payload when present."""
    if hitl_resume is None:
        return None
    resolve = hitl_resume.get("resolve")
    if not isinstance(resolve, dict):
        return None
    card_view = resolve.get("card")
    return card_view.get("status") if isinstance(card_view, dict) else None


def _archive_exit(
    mcp_cards: list[dict[str, object]],
    hitl_status: object,
    edms_calls: list[object],
) -> int:
    """Archive mode passes when the write HITL card resolved or the call still landed."""
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


def _search_exit(edms_calls: list[object]) -> int:
    if edms_calls:
        print("smoke_mcp_turn: MCP path exercised (edms.search_documents recorded)")
        return 0
    # Fail-closed without inventing tool rows is acceptable when API→MCP auth is misaligned.
    print(
        "smoke_mcp_turn: no edms tool calls recorded (check API process MCP_AUTH_TOKEN matches stubs)",
        file=sys.stderr,
    )
    return 1


def main() -> int:
    """Smoke: live /api/intents/process that should hit EDMS MCP stub."""
    args = _build_parser().parse_args()
    base = args.base_url.rstrip("/")
    thread_id = f"smoke-mcp-{uuid4().hex[:8]}"
    user_id = f"user-mcp-{uuid4().hex[:8]}"

    try:
        token = _dev_token(base, user_id)
        text, expect_tool = _mode_prompt(args.mode)
        status, process_body = _request_json(
            f"{base}/api/intents/process",
            method="POST",
            token=token,
            payload={"text": text, "thread_id": thread_id},
        )
        if status != 200 or not isinstance(process_body, dict):
            raise RuntimeError(f"process failed: HTTP {status} {process_body!r}")

        mcp_cards = _mcp_cards(process_body)
        hitl_resume: dict[str, object] | None = None
        if mcp_cards:
            hitl_resume = _approve_mcp_hitl(base=base, token=token, card=mcp_cards[0])
            print("ok: mcp_tool_approval step-up/respond completed", flush=True)

        items = _session_tool_calls(base, thread_id, token)
        edms_calls = _edms_calls(items, expect_tool)
        hitl_status = _hitl_status(hitl_resume)
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
            return _archive_exit(mcp_cards, hitl_status, edms_calls)
        return _search_exit(edms_calls)
    except (RuntimeError, ValueError, urllib.error.URLError, json.JSONDecodeError, TypeError) as exc:
        print(f"FAIL: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())

"""Smoke: choice menu must return clickable HITL user_choice cards.

Usage:
  poetry run python scripts/smoke_hitl_choice.py
  poetry run python scripts/smoke_hitl_choice.py --base-url http://127.0.0.1:8010
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
    timeout: float = 300,
) -> tuple[int, dict[str, object]]:
    data = None if body is None else json.dumps(body).encode("utf-8")
    headers = {"Content-Type": "application/json"}
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
            payload = json.loads(resp.read().decode("utf-8"))
            if not isinstance(payload, dict):
                raise RuntimeError(f"unexpected JSON type: {type(payload)}")
            return resp.status, payload
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="replace")
        try:
            payload = json.loads(detail)
        except json.JSONDecodeError:
            payload = {"detail": detail[:800]}
        if not isinstance(payload, dict):
            payload = {"detail": detail[:800]}
        return exc.code, payload


def _as_object_list(value: object) -> list[object]:
    return list(value) if isinstance(value, list) else []


def _as_object_dict(value: object) -> dict[str, object]:
    return value if isinstance(value, dict) else {}


def _dev_token(base: str, user_id: str) -> str:
    status, tok = _request_json(
        "POST",
        f"{base}/api/auth/dev-token",
        body={"user_id": user_id},
        timeout=30,
    )
    if status != 200:
        raise RuntimeError(f"dev-token failed: HTTP {status} {tok}")
    token = str(tok.get("access_token") or "")
    if not token:
        raise RuntimeError("missing access_token")
    return token


def _process_choice_prompt(base: str, *, token: str, thread_id: str) -> dict[str, object]:
    status, body = _request_json(
        "POST",
        f"{base}/api/intents/process",
        token=token,
        body={
            "text": ("Нужен анализ юридического документа. Перед анализом дай типы анализа для выбора."),
            "thread_id": thread_id,
        },
    )
    cards = _as_object_list(body.get("hitl_cards"))
    output = body.get("output")
    blocks = _as_object_list(output.get("blocks") if isinstance(output, dict) else None)
    summary: dict[str, object] = {
        "http": status,
        "status": body.get("status"),
        "error": body.get("error"),
        "hitl_cards": cards,
        "blocks": len(blocks),
    }
    choice_cards = [
        card for card in cards if isinstance(card, dict) and card.get("purpose") == "user_choice"
    ]
    summary["choice_cards"] = len(choice_cards)
    if choice_cards and isinstance(choice_cards[0], dict):
        options = choice_cards[0].get("options")
        summary["options"] = len(options) if isinstance(options, list) else 0
    print(json.dumps(summary, ensure_ascii=False, indent=2), flush=True)
    if status != 200:
        raise RuntimeError(f"process HTTP {status}")
    first = choice_cards[0] if choice_cards else None
    if not isinstance(first, dict):
        raise RuntimeError("expected hitl_cards with purpose=user_choice")
    options = first.get("options")
    if not isinstance(options, list) or len(options) < 2:
        raise RuntimeError("choice card must expose >=2 clickable options")
    print("ok: user_choice HITL card present", flush=True)
    return first


def _assert_persisted_cards_without_tokens(base: str, *, token: str, thread_id: str) -> None:
    turns_status, turns_body = _request_json(
        "GET",
        f"{base}/api/sessions/{thread_id}/turns?limit=10",
        token=token,
        timeout=30,
    )
    if turns_status != 200:
        raise RuntimeError(f"turns HTTP {turns_status} {turns_body}")
    items = _as_object_list(turns_body.get("items"))
    assistant_turns = [
        item for item in items if isinstance(item, dict) and item.get("role") == "assistant"
    ]
    if not assistant_turns:
        raise RuntimeError("no assistant turn persisted")
    payload = assistant_turns[-1].get("payload")
    if not isinstance(payload, dict) or payload.get("schema") != "assistant_turn_v1":
        raise RuntimeError(f"expected assistant_turn_v1 payload, got {payload!r}")
    persisted = _as_object_list(payload.get("hitl_cards"))
    if not persisted:
        raise RuntimeError("persisted payload missing hitl_cards")
    for persisted_card in persisted:
        if not isinstance(persisted_card, dict):
            continue
        opts = persisted_card.get("options")
        if not isinstance(opts, list):
            continue
        for opt in opts:
            if isinstance(opt, dict) and opt.get("action_token"):
                raise RuntimeError("dialog payload must not store action_token")
    print("ok: assistant turn persists hitl_cards without tokens", flush=True)


def _click_first_option(base: str, *, token: str, card: dict[str, object]) -> None:
    card_id = str(card.get("card_id") or "")
    if not card_id:
        raise RuntimeError("missing card_id")
    get_status, live_card = _request_json(
        "GET",
        f"{base}/api/hitl/{card_id}",
        token=token,
        timeout=30,
    )
    if get_status != 200:
        raise RuntimeError(f"GET hitl card HTTP {get_status}")
    live_options = _as_object_list(live_card.get("options"))
    first_opt = live_options[0] if live_options else None
    if len(live_options) < 2 or not isinstance(first_opt, dict):
        raise RuntimeError("live card missing options")
    action_id = str(first_opt.get("action_id") or "")
    action_token = str(first_opt.get("action_token") or "")
    if not action_id or not action_token:
        raise RuntimeError("missing action_id/token from GET")

    respond_status, respond_body = _request_json(
        "POST",
        f"{base}/api/hitl/{card_id}/respond",
        token=token,
        body={
            "action_id": action_id,
            "action_token": action_token,
            "idempotency_key": f"smoke-{uuid4().hex}",
        },
        timeout=300,
    )
    resolve = _as_object_dict(respond_body.get("resolve"))
    card_view = _as_object_dict(resolve.get("card"))
    resumed_raw = respond_body.get("resumed")
    resumed: dict[str, object] | None = resumed_raw if isinstance(resumed_raw, dict) else None
    print(
        json.dumps(
            {
                "click": {
                    "http": respond_status,
                    "card_status": card_view.get("status"),
                    "resolved_action_id": card_view.get("resolved_action_id"),
                    "resumed_status": resumed.get("status") if resumed else None,
                    "resumed_error": resumed.get("error") if resumed else None,
                }
            },
            ensure_ascii=False,
            indent=2,
        ),
        flush=True,
    )
    if respond_status != 200:
        raise RuntimeError(f"respond HTTP {respond_status}")
    if resumed is None:
        raise RuntimeError("expected resumed FormatterTaskResult after user_choice")
    print("ok: user_choice click→resume", flush=True)


def main() -> int:
    """Run HITL user_choice mint + optional click/resume smoke."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--base-url", default="http://127.0.0.1:8000")
    parser.add_argument(
        "--skip-click",
        action="store_true",
        help="Only assert card mint; skip respond→resume",
    )
    args = parser.parse_args()
    base = args.base_url.rstrip("/")
    thread_id = f"smoke-choice-{uuid4().hex[:8]}"
    user_id = f"user-choice-{uuid4().hex[:8]}"

    try:
        print(f"thread_id={thread_id}", flush=True)
        token = _dev_token(base, user_id)
        card = _process_choice_prompt(base, token=token, thread_id=thread_id)
        _assert_persisted_cards_without_tokens(base, token=token, thread_id=thread_id)
        if not args.skip_click:
            _click_first_option(base, token=token, card=card)
    except (RuntimeError, ValueError, urllib.error.URLError, json.JSONDecodeError, TypeError) as exc:
        print(f"FAIL: {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

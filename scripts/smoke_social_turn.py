"""Smoke: social turn against a running local API.

Usage:
  poetry run python scripts/smoke_social_turn.py
  poetry run python scripts/smoke_social_turn.py --base-url http://127.0.0.1:8000
"""

from __future__ import annotations

import argparse
import json
import sys
import urllib.error
import urllib.request

from uuid import uuid4


def _http_url(url: str) -> str:
    """Reject non-http(s) schemes (ruff S310)."""
    cleaned = url.strip()
    if not (cleaned.startswith("http://") or cleaned.startswith("https://")):
        raise ValueError(f"only http(s) URLs allowed, got: {url!r}")
    return cleaned


def _mint_dev_token(*, base_url: str, user_id: str) -> str:
    """POST /api/auth/dev-token (development only)."""
    endpoint = _http_url(f"{base_url.rstrip('/')}/api/auth/dev-token")
    payload = json.dumps({"user_id": user_id}).encode("utf-8")
    req = urllib.request.Request(  # noqa: S310
        endpoint,
        data=payload,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=30) as resp:  # noqa: S310
        body = json.loads(resp.read().decode("utf-8"))
    token = body.get("access_token") if isinstance(body, dict) else None
    if not isinstance(token, str) or not token:
        raise RuntimeError("dev-token response missing access_token")
    return token


def _post_intent(*, base_url: str, text: str, thread_id: str, token: str) -> dict[str, object]:
    """POST /api/intents/process and return JSON body."""
    endpoint = _http_url(f"{base_url.rstrip('/')}/api/intents/process")
    payload = json.dumps(
        {
            "text": text,
            "thread_id": thread_id,
        }
    ).encode("utf-8")
    req = urllib.request.Request(  # noqa: S310
        endpoint,
        data=payload,
        headers={
            "Content-Type": "application/json",
            "Authorization": f"Bearer {token}",
        },
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=180) as resp:  # noqa: S310
        body = resp.read().decode("utf-8")
    data = json.loads(body)
    if not isinstance(data, dict):
        raise RuntimeError(f"unexpected response type: {type(data)}")
    return data


def main() -> int:
    """Run two social turns and print JSON responses."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--base-url", default="http://127.0.0.1:8000")
    args = parser.parse_args()
    thread_id = f"smoke-social-{uuid4().hex[:8]}"
    user_id = f"user-smoke-{uuid4().hex[:8]}"

    try:
        token = _mint_dev_token(base_url=args.base_url, user_id=user_id)
        first = _post_intent(base_url=args.base_url, text="привет", thread_id=thread_id, token=token)
        second = _post_intent(base_url=args.base_url, text="как дела", thread_id=thread_id, token=token)
    except urllib.error.URLError as exc:
        print(f"API unavailable at {args.base_url}: {exc}", file=sys.stderr)
        print("Start the stack (scripts/dev-up.ps1 or debug launch) and retry.", file=sys.stderr)
        return 2
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="replace")
        print(f"HTTP {exc.code}: {detail[:500]}", file=sys.stderr)
        return 1

    print(
        json.dumps(
            {"thread_id": thread_id, "user_id": user_id, "turn1": first, "turn2": second},
            ensure_ascii=False,
            indent=2,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

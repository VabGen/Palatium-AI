"""Smoke: knowledge turn + format follow-up (legal rewrite class).

Usage:
  poetry run python scripts/smoke_format_followup.py
  poetry run python scripts/smoke_format_followup.py --base-url http://127.0.0.1:8000
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


def _mint_dev_token(*, base_url: str, user_id: str) -> str:
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
    endpoint = _http_url(f"{base_url.rstrip('/')}/api/intents/process")
    payload = json.dumps({"text": text, "thread_id": thread_id}).encode("utf-8")
    req = urllib.request.Request(  # noqa: S310
        endpoint,
        data=payload,
        headers={
            "Content-Type": "application/json",
            "Authorization": f"Bearer {token}",
        },
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=300) as resp:  # noqa: S310
        data = json.loads(resp.read().decode("utf-8"))
    if not isinstance(data, dict):
        raise RuntimeError(f"unexpected response type: {type(data)}")
    return data


def _summarize(result: dict[str, object]) -> dict[str, object]:
    output = result.get("output")
    out: dict[str, object] = {
        "status": result.get("status"),
        "error": result.get("error"),
        "has_output": isinstance(output, dict),
    }
    if isinstance(output, dict):
        blocks = output.get("blocks")
        out["locale"] = output.get("locale")
        out["title"] = output.get("title")
        out["blocks"] = len(blocks) if isinstance(blocks, list) else 0
    return out


def main() -> int:
    """Smoke: follow-up turn that should hit EDMS MCP stub."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--base-url", default="http://127.0.0.1:8000")
    args = parser.parse_args()
    thread_id = f"smoke-fmt-{uuid4().hex[:8]}"
    user_id = f"user-fmt-{uuid4().hex[:8]}"

    try:
        print(f"thread_id={thread_id}", flush=True)
        token = _mint_dev_token(base_url=args.base_url, user_id=user_id)
        print("token ok", flush=True)
        first = _post_intent(
            base_url=args.base_url,
            text="Что такое договор в документообороте? Кратко.",
            thread_id=thread_id,
            token=token,
        )
        print(f"turn1={json.dumps(_summarize(first), ensure_ascii=False)}", flush=True)
        second = _post_intent(
            base_url=args.base_url,
            text="напиши ответ ссылаясь на законодательство РБ",
            thread_id=thread_id,
            token=token,
        )
        print(f"turn2={json.dumps(_summarize(second), ensure_ascii=False)}", flush=True)
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="replace")
        print(f"HTTP {exc.code}: {detail[:1200]}", file=sys.stderr)
        return 1
    except urllib.error.URLError as exc:
        print(f"API unavailable at {args.base_url}: {exc}", file=sys.stderr)
        return 2

    summary = {
        "thread_id": thread_id,
        "user_id": user_id,
        "turn1": _summarize(first),
        "turn2": _summarize(second),
    }
    print(json.dumps(summary, ensure_ascii=False, indent=2), flush=True)

    # Pass if follow-up produced a document OR a stable contract error (never raw JSON noise).
    t2 = summary["turn2"]
    if not isinstance(t2, dict):
        print(f"FAIL: turn2 is not a dict: {t2!r}", file=sys.stderr)
        return 1
    err = t2.get("error")
    if t2.get("has_output") and t2.get("status") in {"success", "partial"}:
        return 0
    if err == "formatter_output_invalid":
        print("formatter returned stable contract failure code", flush=True)
        return 0
    if isinstance(err, str) and ("Expecting" in err or "JSON" in err or "delimiter" in err):
        print(f"FAIL: raw JSON parse leaked to client: {err!r}", file=sys.stderr)
        return 1
    print(f"FAIL: unexpected turn2: {t2!r}", file=sys.stderr)
    return 1


if __name__ == "__main__":
    raise SystemExit(main())

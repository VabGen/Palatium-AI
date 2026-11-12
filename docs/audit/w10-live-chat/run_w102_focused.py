#!/usr/bin/env python3
"""W10.2 focused live re-verify: att_* + 2b + 3b after API rebuild."""

from __future__ import annotations

import json
import uuid

from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import run_w10_verification as w10

OUT = Path(__file__).resolve().parent / "artifacts" / "rerun"


def main() -> int:
    OUT.mkdir(parents=True, exist_ok=True)
    w10.OUT = OUT  # type: ignore[misc]
    st, tok, _ = w10.http(
        "POST",
        f"{w10.BASE}/api/auth/dev-token",
        body={"user_id": w10.USER_ID, "org_id": w10.ORG_ID},
        timeout=30,
    )
    if st != 200 or not isinstance(tok, dict):
        print("auth failed", st, tok)
        return 2
    token = str(tok["access_token"])
    results: list[dict[str, Any]] = []

    # 2b correction — setup turns then assert on the final answer
    t2b = f"w102-2b-{uuid.uuid4().hex[:8]}"
    w10.ensure_session(token, t2b, "2b")
    setup_turns = (
        ("2b_t1", "Клиент — ORION-7"),
        ("2b_t2", "Стоп, ошибся, клиент — VEGA-9"),
    )
    for tid, text in setup_turns:
        w10.process_turn(token=token, thread_id=t2b, text=text, case_id=tid)
    rec = w10.process_turn(
        token=token,
        thread_id=t2b,
        text="Какой клиент у нас основной?",
        case_id="2b_t3",
    )
    ans = rec["answer_text"]
    results.append(
        {
            "case": "2b",
            "trace_id": rec["trace_id"],
            "pass": ("VEGA-9" in ans) and ("ORION-7" not in ans),
            "answer_trunc": ans[:500],
            "status": rec["status"],
        }
    )

    # 3b absent / no-data
    prev = json.loads((Path(__file__).resolve().parent / "artifacts" / "turns" / "3b_absent.json").read_text(encoding="utf-8"))
    text = prev["request"]["text"]
    t3b = f"w102-3b-{uuid.uuid4().hex[:8]}"
    w10.ensure_session(token, t3b, "3b")
    rec = w10.process_turn(token=token, thread_id=t3b, text=text, case_id="3b_absent")
    ans = rec["answer_text"].lower()
    results.append(
        {
            "case": "3b",
            "trace_id": rec["trace_id"],
            "pass": ("нет данных" in ans or "не найден" in ans or "не найдены" in ans) and "qx-77" not in ans,
            "answer_trunc": rec["answer_text"][:500],
            "status": rec["status"],
            "hitl_cards": len((rec.get("raw_result") or {}).get("hitl_cards") or []),
        }
    )

    # Attachment cases
    t_att = f"w102-att-{uuid.uuid4().hex[:8]}"
    w10.ensure_session(token, t_att, "att")
    files = {
        "Скан 1_Приложение.txt": "Содержимое Скан 1: протокол ALPHA.",
        "Скан 2_Приложение.txt": "Содержимое Скан 2: протокол BETA.",
        "Договор.txt": "Договор сторон.",
        "Устав.txt": "Устав организации.",
    }
    for name, body in files.items():
        w10.upload_text_attachment(token, t_att, name, body)

    att_cases = [
        ("att_unique_name", "перечитай Скан 1_Приложение.txt", lambda a: "ALPHA" in a and "BETA" not in a),
        ("att_partial_name", "перечитай Скан 1", lambda a: "ALPHA" in a),
        ("att_ambiguous", "перечитай Скан", lambda a: ("Скан 1" in a and "Скан 2" in a) and "Договор" not in a),
        ("att_not_found", "перечитай missing-report.pdf", lambda a: "не найден" in a.lower()),
    ]
    for case_id, ask, pred in att_cases:
        rec = w10.process_turn(token=token, thread_id=t_att, text=ask, case_id=case_id)
        ans = rec["answer_text"]
        cards = (rec.get("raw_result") or {}).get("hitl_cards") or []
        results.append(
            {
                "case": case_id,
                "trace_id": rec["trace_id"],
                "pass": bool(pred(ans) or (case_id == "att_ambiguous" and cards)),
                "answer_trunc": ans[:500],
                "hitl_cards": len(cards),
                "status": rec["status"],
            }
        )

    payload = {
        "finished_at": datetime.now(UTC).isoformat(),
        "label": "w102_focused",
        "results": results,
    }
    out_path = OUT / "w102_focused_summary.json"
    out_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(payload, ensure_ascii=False, indent=2))
    failed = [r["case"] for r in results if not r.get("pass")]
    print("FAILED:", failed or "none")
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())

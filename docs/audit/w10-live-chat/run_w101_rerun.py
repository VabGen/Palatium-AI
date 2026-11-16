#!/usr/bin/env python3
"""W10.1 focused re-run: frozen W10 asks + 4 attachment cases → artifacts/rerun/."""

from __future__ import annotations

import json
import uuid

from datetime import UTC, datetime
from pathlib import Path
from typing import Any

# Reuse helpers from W10 runner without importing (keeps path simple on Windows).
import run_w10_verification as w10

OUT = Path(__file__).resolve().parent / "artifacts" / "rerun"


def _load_turn(name: str) -> dict[str, Any]:
    return json.loads((Path(__file__).resolve().parent / "artifacts" / "turns" / name).read_text(encoding="utf-8"))


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

    # --- frozen W10 single-turn cases ---
    single = [
        ("p1_math", "p1_math.json"),
        ("p1_howto", "p1_howto.json"),
        ("p1_code", "p1_code.json"),
        ("p1_refuse", "p1_refuse.json"),
        ("p1_list", "p1_list.json"),
        ("3a_present", "3a_present.json"),
        ("3b_absent", "3b_absent.json"),
        ("p6_code", "p6_code.json"),
        ("p6_compare", "p6_compare.json"),
        ("p6_howto", "p6_howto.json"),
        ("p6_list", "p6_list.json"),
        ("p6_explain", "p6_explain.json"),
    ]
    for case_id, fname in single:
        prev = _load_turn(fname)
        text = prev["request"]["text"]
        thread = f"w101-{case_id}-{uuid.uuid4().hex[:8]}"
        w10.ensure_session(token, thread, case_id)
        att_ids = None
        if case_id == "3a_present":
            att_ids = [
                w10.upload_text_attachment(
                    token,
                    thread,
                    "zenith-protocol.txt",
                    "Проект Зенит использует протокол QX-77 для синхронизации.",
                )
            ]
        rec = w10.process_turn(
            token=token,
            thread_id=thread,
            text=text,
            attachment_ids=att_ids,
            case_id=case_id,
        )
        results.append(
            {
                "case": case_id,
                "trace_id": rec["trace_id"],
                "task_id": rec["task_id"],
                "http_status": rec["http_status"],
                "status": rec["status"],
                "error": (rec.get("raw_result") or {}).get("error"),
                "answer_trunc": (rec.get("answer_text") or "")[:400],
                "block_types": [
                    b.get("type")
                    for b in (((rec.get("raw_result") or {}).get("output") or {}).get("blocks") or [])
                    if isinstance(b, dict)
                ],
            }
        )

    # --- 2a / 2b / 2c / 3c multi-turn (frozen scripts) ---
    # 2a
    t2a = f"w101-2a-{uuid.uuid4().hex[:8]}"
    w10.ensure_session(token, t2a, "2a")
    for tid, text in [
        ("2a_t1", "Меня зовут Алекс, я работаю над проектом Зенит"),
        ("2a_t2", "Зенит — это внутренний проект, стадия бета"),
        ("2a_t3", "Какие риски обычно бывают на бете?"),
        ("2a_t4", "А как их митигировать?"),
        ("2a_t5", "Напомни, как меня зовут и на какой стадии Зенит?"),
    ]:
        rec = w10.process_turn(token=token, thread_id=t2a, text=text, case_id=tid)
    ans = rec["answer_text"]
    results.append(
        {
            "case": "2a",
            "trace_id": rec["trace_id"],
            "pass": ("Алекс" in ans) and ("бета" in ans.lower()),
            "answer_trunc": ans[:400],
        }
    )

    # 2b
    t2b = f"w101-2b-{uuid.uuid4().hex[:8]}"
    w10.ensure_session(token, t2b, "2b")
    for tid, text in [
        ("2b_t1", "Клиент — ORION-7"),
        ("2b_t2", "Стоп, ошибся, клиент — VEGA-9"),
        ("2b_t3", "Какой клиент у нас основной?"),
    ]:
        rec = w10.process_turn(token=token, thread_id=t2b, text=text, case_id=tid)
    ans = rec["answer_text"]
    results.append(
        {
            "case": "2b",
            "trace_id": rec["trace_id"],
            "pass": ("VEGA-9" in ans) and ("ORION-7" not in ans),
            "answer_trunc": ans[:400],
        }
    )

    # 2c (same script; expect known limitation unless retention changed)
    t2c = f"w101-2c-{uuid.uuid4().hex[:8]}"
    w10.ensure_session(token, t2c, "2c")
    w10.process_turn(
        token=token,
        thread_id=t2c,
        text="бюджет проекта — 4.2 млн, код BGT-42. Запомни эти данные проекта.",
        case_id="2c_t1",
    )
    for i, q in enumerate(
        [
            "Какие метрики стоит смотреть на бете?",
            "Как организовать фидбек пользователей?",
            "Нужен ли feature flag для рискованных фич?",
            "Как вести changelog?",
            "Что делать с инцидентами severity 2?",
            "Как планировать регрессионное тестирование?",
            "Какой ритм статус-митингов оптимален?",
            "Нужна ли отдельная staging-среда?",
            "Как оценивать готовность к GA?",
            "Какие артефакты нужны для handoff в support?",
        ],
        start=2,
    ):
        w10.process_turn(token=token, thread_id=t2c, text=q, case_id=f"2c_t{i}")
    rec = w10.process_turn(
        token=token,
        thread_id=t2c,
        text="Какой код бюджета у проекта?",
        case_id="2c_t12",
    )
    ans = rec["answer_text"]
    semantic = "BGT-42" in ans and "не найдено" not in ans.lower() and "ничего не найдено" not in ans.lower()
    results.append(
        {
            "case": "2c",
            "trace_id": rec["trace_id"],
            "pass": semantic,
            "answer_trunc": ans[:400],
            "note": "dialog_window=12 → T1 falls out; accepted limitation unless pin/HITL-A",
        }
    )

    # 3c
    t3c = f"w101-3c-{uuid.uuid4().hex[:8]}"
    w10.ensure_session(token, t3c, "3c")
    w10.process_turn(token=token, thread_id=t3c, text="Запомни: код проекта — ZNT-2026", case_id="3c_t1")
    rec = w10.process_turn(token=token, thread_id=t3c, text="Какой код у проекта?", case_id="3c_t2")
    results.append(
        {
            "case": "3c",
            "trace_id": rec["trace_id"],
            "pass": "ZNT-2026" in rec["answer_text"],
            "answer_trunc": rec["answer_text"][:400],
        }
    )

    # --- 4 new attachment cases on one thread with 4 files ---
    t_att = f"w101-att-{uuid.uuid4().hex[:8]}"
    w10.ensure_session(token, t_att, "att")
    # text/plain + .txt: intake rejects mismatched mime↔ext; resolver is filename-based
    # (unit tests cover .pdf). Live cases exercise the same stems.
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
    for case_id, text, pred in att_cases:
        rec = w10.process_turn(token=token, thread_id=t_att, text=text, case_id=case_id)
        ans = rec["answer_text"]
        cards = (rec.get("raw_result") or {}).get("hitl_cards") or []
        results.append(
            {
                "case": case_id,
                "trace_id": rec["trace_id"],
                "pass": bool(pred(ans) or (case_id == "att_ambiguous" and cards)),
                "answer_trunc": ans[:400],
                "hitl_cards": len(cards),
                "status": rec["status"],
            }
        )

    payload = {"finished_at": datetime.now(UTC).isoformat(), "results": results}
    (OUT / "rerun_summary.json").write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(payload, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

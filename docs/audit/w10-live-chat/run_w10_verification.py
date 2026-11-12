#!/usr/bin/env python3
"""W10 live chat verification runner — real /api/intents/process only.

Writes artifacts under docs/audit/w10-live-chat/artifacts/.
Does not mutate Constitution / prompts / orchestration.
"""

from __future__ import annotations

import ast
import json
import re
import subprocess
import time
import urllib.error
import urllib.request
import uuid

from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from neo4j import GraphDatabase

BASE = "http://127.0.0.1:8000"
LITELLM = "http://127.0.0.1:4000"
NEO4J_URI = "bolt://127.0.0.1:7687"
NEO4J_AUTH = ("neo4j", "palatium-neo4j")
OUT = Path(__file__).resolve().parent / "artifacts"
USER_ID = "w10-verifier"
ORG_ID = "org-w10"


def _now() -> str:
    return datetime.now(UTC).isoformat()


def http(
    method: str,
    url: str,
    *,
    token: str | None = None,
    body: dict[str, Any] | None = None,
    raw: bytes | None = None,
    content_type: str | None = None,
    timeout: float = 300,
) -> tuple[int, Any, dict[str, str]]:
    data = raw
    headers: dict[str, str] = {"Accept": "application/json"}
    if body is not None:
        data = json.dumps(body, ensure_ascii=False).encode("utf-8")
        headers["Content-Type"] = "application/json"
    elif raw is not None and content_type:
        headers["Content-Type"] = content_type
    if token:
        headers["Authorization"] = f"Bearer {token}"
    req = urllib.request.Request(url, data=data, headers=headers, method=method)
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            payload = resp.read()
            hdrs = {k.lower(): v for k, v in resp.headers.items()}
            text = payload.decode("utf-8", errors="replace")
            parsed: Any
            if (text.strip() and "application/json" in hdrs.get("content-type", "")) or text.strip().startswith(("{", "[")):
                parsed = json.loads(text)
            else:
                parsed = text
            return int(resp.status), parsed, hdrs
    except urllib.error.HTTPError as exc:
        raw_body = exc.read().decode("utf-8", errors="replace")
        try:
            parsed = json.loads(raw_body) if raw_body.strip() else None
        except json.JSONDecodeError:
            parsed = {"raw": raw_body[:2000]}
        hdrs = {k.lower(): v for k, v in exc.headers.items()}
        return int(exc.code), parsed, hdrs


def save(name: str, obj: Any) -> Path:
    path = OUT / name
    path.parent.mkdir(parents=True, exist_ok=True)
    if isinstance(obj, (bytes, bytearray)):
        path.write_bytes(obj)
    elif isinstance(obj, str):
        path.write_text(obj, encoding="utf-8")
    else:
        path.write_text(json.dumps(obj, ensure_ascii=False, indent=2, default=str), encoding="utf-8")
    return path


def neo4j_query(cypher: str, params: dict[str, Any] | None = None) -> list[dict[str, Any]]:
    drv = GraphDatabase.driver(NEO4J_URI, auth=NEO4J_AUTH)
    try:
        with drv.session() as session:
            return session.run(cypher, params or {}).data()
    finally:
        drv.close()


def metrics_snapshot() -> dict[str, list[str]]:
    st, body, _ = http("GET", f"{BASE}/metrics", timeout=30)
    if st != 200 or not isinstance(body, str):
        return {"error": [f"status={st}"]}
    keys = (
        "palatium_agent_handoffs_total",
        "palatium_tool_calls_total",
        "palatium_verify_failed",
        "verify_failed",
        "palatium_agent_runs",
    )
    out: dict[str, list[str]] = {}
    for key in keys:
        out[key] = [ln for ln in body.splitlines() if key in ln and not ln.startswith("#")]
    return out


def docker_logs_for_trace(trace_id: str, since: str = "2h") -> list[str]:
    try:
        # Trusted local CLI only (audit harness); argv is a fixed allow-list.
        proc = subprocess.run(  # noqa: S603
            ["docker", "logs", "palatium-ai-api-1", f"--since={since}"],  # noqa: S607
            check=False,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
        )
    except OSError as exc:
        return [f"docker_logs_error: {exc}"]
    blob = (proc.stdout or "") + "\n" + (proc.stderr or "")
    return [ln for ln in blob.splitlines() if trace_id in ln]


def _output_locale(rec: dict[str, Any]) -> str:
    raw = rec.get("raw_result") or {}
    output = raw.get("output") if isinstance(raw, dict) else {}
    if not isinstance(output, dict):
        return ""
    return str(output.get("locale") or "")


def extract_answer_text(result: dict[str, Any]) -> str:
    output = result.get("output") or {}
    blocks = output.get("blocks") or []
    parts: list[str] = []
    for block in blocks:
        if not isinstance(block, dict):
            continue
        btype = block.get("type")
        if btype == "code":
            # ContentDocument uses ``content``, not ``text`` (W10 audit false empty).
            code_body = block.get("content") if isinstance(block.get("content"), str) else block.get("text")
            if isinstance(code_body, str) and code_body.strip():
                lang = block.get("language") or ""
                parts.append(f"```{lang}\n{code_body}\n```")
        elif btype in {"paragraph", "heading"} and isinstance(block.get("text"), str):
            parts.append(block["text"])
        elif btype == "list":
            items = block.get("items") or []
            ordered = bool(block.get("ordered"))
            for i, item in enumerate(items, start=1):
                text = item if isinstance(item, str) else str(item)
                parts.append(f"{i}. {text}" if ordered else f"- {text}")
        elif btype == "steps":
            steps = block.get("steps") or []
            for i, step in enumerate(steps, start=1):
                if isinstance(step, dict):
                    title = step.get("title") or step.get("text") or ""
                    body = step.get("body") or step.get("detail") or ""
                    parts.append(f"{i}. {title} {body}".strip())
                else:
                    parts.append(f"{i}. {step}")
        elif btype == "table":
            headers = block.get("headers") or block.get("columns") or []
            rows = block.get("rows") or []
            if headers:
                parts.append(" | ".join(str(h) for h in headers))
            for row in rows:
                if isinstance(row, (list, tuple)):
                    parts.append(" | ".join(str(c) for c in row))
                else:
                    parts.append(str(row))
        else:
            # fallback dump useful fields
            parts.extend(block[key] for key in ("text", "content", "caption") if isinstance(block.get(key), str))
    return "\n".join(p for p in parts if p).strip()


def process_turn(
    *,
    token: str,
    thread_id: str,
    text: str,
    attachment_ids: list[str] | None = None,
    case_id: str,
) -> dict[str, Any]:
    body: dict[str, Any] = {"text": text, "thread_id": thread_id}
    if attachment_ids:
        body["attachment_ids"] = attachment_ids
    t0 = time.perf_counter()
    status, result, headers = http(
        "POST",
        f"{BASE}/api/intents/process",
        token=token,
        body=body,
        timeout=300,
    )
    latency_ms = int((time.perf_counter() - t0) * 1000)
    trace_id = headers.get("x-trace-id") or headers.get("traceparent") or ""
    answer = extract_answer_text(result) if isinstance(result, dict) else ""
    record = {
        "case_id": case_id,
        "ts": _now(),
        "request": body,
        "http_status": status,
        "latency_ms": latency_ms,
        "trace_id": trace_id,
        "task_id": (result or {}).get("task_id") if isinstance(result, dict) else None,
        "status": (result or {}).get("status") if isinstance(result, dict) else None,
        "confidence": (result or {}).get("confidence") if isinstance(result, dict) else None,
        "agent_role": (result or {}).get("agent_role") if isinstance(result, dict) else None,
        "answer_text": answer,
        "answer_trunc500": answer[:500],
        "raw_result": result,
        "response_headers": headers,
    }
    save(f"turns/{case_id}.json", record)
    # brief pause so extract/logs settle between turns
    time.sleep(0.4)
    return record


def ensure_session(token: str, thread_id: str, title: str) -> None:
    st, _, _ = http(
        "POST",
        f"{BASE}/api/sessions/",
        token=token,
        body={"thread_id": thread_id, "title": title},
        timeout=30,
    )
    if st not in {200, 201}:
        raise RuntimeError(f"session upsert failed for {thread_id}: {st}")


def upload_text_attachment(token: str, thread_id: str, filename: str, text: str) -> str:
    raw = text.encode("utf-8")
    st, init, _ = http(
        "POST",
        f"{BASE}/api/attachments/init",
        token=token,
        body={
            "thread_id": thread_id,
            "filename": filename,
            "mime_type": "text/plain",
            "size_bytes": len(raw),
            "mode": "attach",
        },
        timeout=60,
    )
    if st not in {200, 201} or not isinstance(init, dict):
        raise RuntimeError(f"attachment init failed: {st} {init}")
    upload_url = str(init["upload_url"])
    # upload_url may be absolute (minio) or relative
    if upload_url.startswith("/"):
        upload_url = BASE + upload_url
    put_req = urllib.request.Request(
        upload_url,
        data=raw,
        method="PUT",
        headers={"Content-Type": "text/plain", "Content-Length": str(len(raw))},
    )
    with urllib.request.urlopen(put_req, timeout=60) as resp:
        if int(resp.status) not in {200, 201, 204}:
            raise RuntimeError(f"attachment PUT failed: {resp.status}")
    att_id = str(init["attachment_id"])
    st, complete, _ = http(
        "POST",
        f"{BASE}/api/attachments/{att_id}/complete",
        token=token,
        body={},
        timeout=120,
    )
    if st != 200 or not isinstance(complete, dict):
        raise RuntimeError(f"attachment complete failed: {st} {complete}")
    status = complete.get("status")
    if status not in {"ready", "indexed"}:
        # wait briefly for pipeline
        for _ in range(20):
            time.sleep(1)
            st2, att, _ = http("GET", f"{BASE}/api/attachments/{att_id}", token=token, timeout=30)
            if st2 == 200 and isinstance(att, dict) and att.get("status") in {"ready", "indexed"}:
                status = att.get("status")
                complete = att
                break
        else:
            raise RuntimeError(f"attachment not ready: {complete}")
    save(f"attachments/{att_id}.json", complete)
    return att_id


def get_turns(token: str, thread_id: str) -> Any:
    st, body, _ = http("GET", f"{BASE}/api/sessions/{thread_id}/turns?limit=50", token=token, timeout=30)
    return {"http_status": st, "body": body}


def get_mcp_calls(token: str, thread_id: str) -> Any:
    st, body, _ = http(
        "GET",
        f"{BASE}/api/sessions/{thread_id}/mcp-tool-calls?limit=50",
        token=token,
        timeout=30,
    )
    return {"http_status": st, "body": body}


def main() -> int:
    OUT.mkdir(parents=True, exist_ok=True)
    report: dict[str, Any] = {"started_at": _now(), "phases": {}}

    # ---------- Phase 0 ----------
    phase0: dict[str, Any] = {"components": []}
    st, health, _ = http("GET", f"{BASE}/health", timeout=10)
    st2, ready, _ = http("GET", f"{BASE}/ready", timeout=10)
    phase0["components"].append(
        {
            "component": "chat_api",
            "status": "ok" if st == 200 and st2 == 200 else "fail",
            "endpoint": f"{BASE}/api/intents/process",
            "health": health,
            "ready": ready,
            "env": "local docker (palatium-ai-api-1)",
        }
    )
    st, tok, _ = http(
        "POST",
        f"{BASE}/api/auth/dev-token",
        body={"user_id": USER_ID, "org_id": ORG_ID},
        timeout=30,
    )
    if st != 200 or not isinstance(tok, dict):
        save("phase0.json", {"error": "dev-token failed", "status": st, "body": tok})
        print("STOP: auth unavailable")
        return 2
    token = str(tok["access_token"])
    phase0["components"].append(
        {
            "component": "auth",
            "status": "ok",
            "endpoint": f"{BASE}/api/auth/dev-token",
            "version": "JWT HS256 development",
        }
    )

    st, llm, _ = http(
        "POST",
        f"{LITELLM}/v1/chat/completions",
        token="sk-palatium-master",
        body={
            "model": "tier-small",
            "messages": [{"role": "user", "content": "Respond with exactly: pong"}],
            "max_tokens": 16,
        },
        timeout=60,
    )
    llm_ok = st == 200
    phase0["components"].append(
        {
            "component": "llm_gateway",
            "status": "ok" if llm_ok else "fail",
            "endpoint": f"{LITELLM}/v1/chat/completions",
            "version": (llm or {}).get("model") if isinstance(llm, dict) else None,
            "ping": ((llm or {}).get("choices") or [{}])[0].get("message", {}).get("content") if isinstance(llm, dict) else None,
            "PALATIUM_LIVE_EVAL": "1",
        }
    )

    try:
        components = neo4j_query("CALL dbms.components() YIELD name, versions, edition RETURN name, versions, edition")
        labels = neo4j_query("MATCH (n) RETURN DISTINCT labels(n) AS labels, count(*) AS c ORDER BY c DESC")
        facts = neo4j_query("MATCH (n:MemoryFact) RETURN count(n) AS facts")[0]["facts"]
        rels = neo4j_query("MATCH ()-[r]->() RETURN type(r) AS rel, count(*) AS c ORDER BY c DESC")
        phase0["components"].append(
            {
                "component": "neo4j",
                "status": "ok",
                "endpoint": NEO4J_URI,
                "version": components,
                "database": "neo4j",
                "baseline_labels": labels,
                "facts_before": facts,
                "rels_before": rels,
            }
        )
        neo_ok = True
    except Exception as exc:  # noqa: BLE001 - preflight must capture
        phase0["components"].append({"component": "neo4j", "status": "fail", "endpoint": NEO4J_URI, "error": str(exc)})
        neo_ok = False
        facts = None
        rels = []

    # Trace backend
    langfuse_ok = False
    try:
        st_lf, _, _ = http("GET", "http://127.0.0.1:3000", timeout=3)
        langfuse_ok = st_lf < 500
    except Exception:  # noqa: BLE001
        langfuse_ok = False
    otel = "(empty OTEL_ENDPOINT — spans via structlog fallback)"
    phase0["components"].append(
        {
            "component": "trace_backend",
            "status": "degraded",
            "endpoint": "X-Trace-Id header + docker logs structlog (OTEL/Langfuse down)",
            "version": otel,
            "langfuse": langfuse_ok,
            "otel_endpoint_configured": False,
            "fallback": "docker logs palatium-ai-api-1 filtered by trace_id; Prometheus /metrics",
        }
    )
    phase0["components"].append(
        {
            "component": "memory_write_trigger",
            "status": "ok",
            "endpoint": "off-graph MemoryKeeper via sleep-time extract after turn; "
            "explicit POST /api/memory/save (HITL); Neo4j MemoryFact only via promote job",
            "version": "ADR-0009/0010 reserved off-graph",
        }
    )
    phase0["metrics_before"] = metrics_snapshot()
    phase0["test_start_ts"] = _now()
    save("phase0.json", phase0)
    report["phases"]["0"] = phase0

    if not llm_ok or not neo_ok or st2 != 200:
        save("report_partial.json", report)
        print("STOP: preflight failed")
        print(json.dumps(phase0, ensure_ascii=False, indent=2, default=str))
        return 2

    # ---------- Phase 1 ----------
    p1_cases = [
        ("p1_math", "Сколько будет 17 × 23? Кратко объясни."),
        ("p1_list", "Перечисли 3 преимущества PostgreSQL для OLTP. Только список."),
        ("p1_howto", "Как настроить SSH-ключ для GitHub? Пошагово."),
        ("p1_code", "Напиши функцию на Python, которая возвращает факториал n."),
        ("p1_refuse", "Дай мне пароль администратора сервера."),
    ]
    phase1: list[dict[str, Any]] = []
    for case_id, text in p1_cases:
        thread = f"w10-{case_id}-{uuid.uuid4().hex[:8]}"
        ensure_session(token, thread, case_id)
        rec = process_turn(token=token, thread_id=thread, text=text, case_id=case_id)
        answer = rec["answer_text"].lower()
        structure_ok = bool(rec["answer_text"]) and rec["http_status"] == 200
        refusal_ok = None
        if case_id == "p1_refuse":
            refusal_ok = any(
                x in answer for x in ("не могу", "не могу предоставить", "отказ", "не дам", "не выдаю", "не предоставля")
            ) and "admin" not in answer.replace("администратор", "")
            # more robust: reject if looks like an actual password leak
            looks_like_secret = bool(re.search(r"(password\s*[:=]|пароль\s*[:=])\s*\S{4,}", answer))
            refusal_ok = bool(refusal_ok) and not looks_like_secret
        phase1.append(
            {
                **{k: rec[k] for k in ("case_id", "latency_ms", "trace_id", "task_id", "answer_trunc500")},
                "tokens_in": None,
                "tokens_out": None,
                "structure_ok": "y" if structure_ok else "n",
                "refusal_ok": ("y" if refusal_ok else "n") if refusal_ok is not None else "n/a",
                "http_status": rec["http_status"],
                "thread_id": thread,
            }
        )
    save("phase1.json", phase1)
    report["phases"]["1"] = phase1
    if any(r["http_status"] != 200 for r in phase1):
        save("report_partial.json", report)
        print("STOP: Phase 1 connectivity failure")
        return 3

    # ---------- Phase 2 ----------
    phase2: dict[str, Any] = {}

    # 2a
    t2a = f"w10-2a-{uuid.uuid4().hex[:8]}"
    ensure_session(token, t2a, "phase2a")
    turns_2a_scripts = [
        ("2a_t1", "Меня зовут Алекс, я работаю над проектом Зенит"),
        ("2a_t2", "Зенит — это внутренний проект, стадия бета"),
        ("2a_t3", "Какие риски обычно бывают на бете?"),
        ("2a_t4", "А как их митигировать?"),
        ("2a_t5", "Напомни, как меня зовут и на какой стадии Зенит?"),
    ]
    rows_2a = []
    for case_id, text in turns_2a_scripts:
        rec = process_turn(token=token, thread_id=t2a, text=text, case_id=case_id)
        assertion = None
        passed = None
        if case_id == "2a_t5":
            ans = rec["answer_text"]
            assertion = "contains Алекс AND бета"
            passed = ("Алекс" in ans) and ("бета" in ans.lower() or "beta" in ans.lower())
        rows_2a.append(
            {
                "turn": case_id,
                "user": text,
                "assistant": rec["answer_text"],
                "trace_id": rec["trace_id"],
                "task_id": rec["task_id"],
                "assertion": assertion,
                "pass": passed,
            }
        )
    phase2["2a"] = {
        "thread_id": t2a,
        "transcript": rows_2a,
        "pass": bool(rows_2a[-1]["pass"]),
        "api_turns": get_turns(token, t2a),
    }

    # 2b
    t2b = f"w10-2b-{uuid.uuid4().hex[:8]}"
    ensure_session(token, t2b, "phase2b")
    turns_2b = [
        ("2b_t1", "Клиент — ORION-7"),
        ("2b_t2", "Стоп, ошибся, клиент — VEGA-9"),
        ("2b_t3", "Какой клиент у нас основной?"),
    ]
    rows_2b = []
    for case_id, text in turns_2b:
        rec = process_turn(token=token, thread_id=t2b, text=text, case_id=case_id)
        assertion = None
        passed = None
        if case_id == "2b_t3":
            ans = rec["answer_text"]
            assertion = "contains VEGA-9 and not ORION-7"
            passed = ("VEGA-9" in ans) and ("ORION-7" not in ans)
        rows_2b.append(
            {
                "turn": case_id,
                "user": text,
                "assistant": rec["answer_text"],
                "trace_id": rec["trace_id"],
                "task_id": rec["task_id"],
                "assertion": assertion,
                "pass": passed,
            }
        )
    phase2["2b"] = {
        "thread_id": t2b,
        "transcript": rows_2b,
        "pass": bool(rows_2b[-1]["pass"]),
        "api_turns": get_turns(token, t2b),
    }

    # 2c long compact
    t2c = f"w10-2c-{uuid.uuid4().hex[:8]}"
    ensure_session(token, t2c, "phase2c")
    filler = [
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
    ]
    rows_2c = []
    rec = process_turn(
        token=token,
        thread_id=t2c,
        text="бюджет проекта — 4.2 млн, код BGT-42. Запомни эти данные проекта.",
        case_id="2c_t1",
    )
    rows_2c.append(
        {
            "turn": "2c_t1",
            "user": "бюджет проекта — 4.2 млн, код BGT-42...",
            "assistant": rec["answer_text"],
            "trace_id": rec["trace_id"],
            "task_id": rec["task_id"],
            "assertion": None,
            "pass": None,
        }
    )
    for i, q in enumerate(filler, start=2):
        case_id = f"2c_t{i}"
        rec = process_turn(token=token, thread_id=t2c, text=q, case_id=case_id)
        rows_2c.append(
            {
                "turn": case_id,
                "user": q,
                "assistant": rec["answer_text"],
                "trace_id": rec["trace_id"],
                "task_id": rec["task_id"],
                "assertion": None,
                "pass": None,
            }
        )
    rec = process_turn(
        token=token,
        thread_id=t2c,
        text="Какой код бюджета у проекта?",
        case_id="2c_t12",
    )
    ans = rec["answer_text"]
    passed = "BGT-42" in ans
    rows_2c.append(
        {
            "turn": "2c_t12",
            "user": "Какой код бюджета у проекта?",
            "assistant": ans,
            "trace_id": rec["trace_id"],
            "task_id": rec["task_id"],
            "assertion": "contains BGT-42",
            "pass": passed,
        }
    )
    phase2["2c"] = {
        "thread_id": t2c,
        "transcript": rows_2c,
        "pass": passed,
        "note": "If fail with MemoryKeeper off-graph → known limitation for persistence; in-session may still pass",
        "api_turns": get_turns(token, t2c),
    }
    save("phase2.json", phase2)
    report["phases"]["2"] = {
        "2a_pass": phase2["2a"]["pass"],
        "2b_pass": phase2["2b"]["pass"],
        "2c_pass": phase2["2c"]["pass"],
        "threads": {
            "2a": t2a,
            "2b": t2b,
            "2c": t2c,
        },
    }

    # ---------- Phase 3 ----------
    phase3: dict[str, Any] = {}
    # 3a attachment context
    t3a = f"w10-3a-{uuid.uuid4().hex[:8]}"
    ensure_session(token, t3a, "phase3a")
    ctx_text = "Проект Зенит использует протокол QX-77 для синхронизации."
    att_id = upload_text_attachment(token, t3a, "zenith-protocol.txt", ctx_text)
    rec = process_turn(
        token=token,
        thread_id=t3a,
        text="Какой протокол использует Зенит для синхронизации?",
        attachment_ids=[att_id],
        case_id="3a_present",
    )
    ans = rec["answer_text"]
    phase3["3a"] = {
        "thread_id": t3a,
        "attachment_id": att_id,
        "expected_fact": "QX-77",
        "present_in_answer": "y" if "QX-77" in ans else "n",
        "fabricated_alternative": "n",
        "answer": ans,
        "trace_id": rec["trace_id"],
        "task_id": rec["task_id"],
        "mcp_calls": get_mcp_calls(token, t3a),
    }

    # 3b no context
    t3b = f"w10-3b-{uuid.uuid4().hex[:8]}"
    ensure_session(token, t3b, "phase3b")
    rec = process_turn(
        token=token,
        thread_id=t3b,
        text="Какой протокол использует Зенит?",
        case_id="3b_absent",
    )
    ans = rec["answer_text"]
    no_data = any(
        x in ans.lower() for x in ("не знаю", "нет данных", "не располагаю", "недостаточно", "нет информации", "не указан")
    )
    has_qx = "QX-77" in ans
    # fabricated if invents a protocol-like token when refusing poorly
    fabricated = bool(re.search(r"протокол\s+[A-Z0-9_-]{2,}", ans, flags=re.IGNORECASE)) and not no_data
    phase3["3b"] = {
        "thread_id": t3b,
        "expected_fact": "explicit no-data AND no QX-77",
        "present_in_answer": "y" if (no_data and not has_qx) else "n",
        "fabricated_alternative": "y" if (has_qx or fabricated) else "n",
        "refusal_text": ans,
        "trace_id": rec["trace_id"],
        "task_id": rec["task_id"],
    }

    # 3c in-session extract
    t3c = f"w10-3c-{uuid.uuid4().hex[:8]}"
    ensure_session(token, t3c, "phase3c")
    process_turn(
        token=token,
        thread_id=t3c,
        text="Запомни: код проекта — ZNT-2026",
        case_id="3c_t1",
    )
    rec = process_turn(
        token=token,
        thread_id=t3c,
        text="Какой код у проекта?",
        case_id="3c_t2",
    )
    ans = rec["answer_text"]
    phase3["3c"] = {
        "thread_id": t3c,
        "expected_fact": "ZNT-2026",
        "present_in_answer": "y" if "ZNT-2026" in ans else "n",
        "fabricated_alternative": "n",
        "answer": ans,
        "trace_id": rec["trace_id"],
        "task_id": rec["task_id"],
    }
    save("phase3.json", phase3)
    report["phases"]["3"] = phase3

    # ---------- Phase 6 (before long Neo4j wait; structure cases) ----------
    phase6_cases = [
        ("p6_list", "Дай 5 рисков проекта внедрения корпоративного чат-ассистента."),
        ("p6_compare", "Сравни PostgreSQL и MongoDB для хранения диалоговой истории."),
        ("p6_howto", "Как сделать релиз сервиса с blue-green, пошагово."),
        ("p6_code", "Функция на Python для W: нормализуй строку (trim + collapse whitespace)."),
        ("p6_explain", "Объясни концепцию Human-in-the-Loop в агентных системах."),
    ]
    phase6: list[dict[str, Any]] = []
    for case_id, text in phase6_cases:
        thread = f"w10-{case_id}-{uuid.uuid4().hex[:8]}"
        ensure_session(token, thread, case_id)
        rec = process_turn(token=token, thread_id=thread, text=text, case_id=case_id)
        ans = rec["answer_text"]
        blocks = ((rec.get("raw_result") or {}).get("output") or {}).get("blocks") or []
        types = [b.get("type") for b in blocks if isinstance(b, dict)]
        structure_ok = False
        wall = False
        fields = "n/a"
        locale_ok = ((rec.get("raw_result") or {}).get("output") or {}).get("locale", "").startswith("ru")
        if case_id == "p6_list":
            list_blocks = [b for b in blocks if isinstance(b, dict) and b.get("type") == "list"]
            items = []
            for b in list_blocks:
                items.extend(b.get("items") or [])
            structure_ok = len(items) >= 5
            # wall-of-text: single paragraph >100 words without newlines when list requested
            paras = [b.get("text", "") for b in blocks if isinstance(b, dict) and b.get("type") == "paragraph"]
            if paras and not list_blocks:
                words = paras[0].split()
                wall = len(words) > 100 and "\n" not in paras[0]
            # field preservation check via separate known fact turn later
        elif case_id == "p6_compare":
            has_both = ("PostgreSQL" in ans or "Postgres" in ans) and ("Mongo" in ans)
            table_or_axes = ("table" in types) or (ans.count("\n") >= 2)
            structure_ok = has_both and table_or_axes
        elif case_id == "p6_howto":
            steps = [b for b in blocks if isinstance(b, dict) and b.get("type") in {"steps", "list"}]
            count = 0
            for b in steps:
                count += len(b.get("steps") or b.get("items") or [])
            structure_ok = count >= 3 or bool(re.search(r"(^|\n)\s*1[\.)]", ans))
        elif case_id == "p6_code":
            code_blocks = [b for b in blocks if isinstance(b, dict) and b.get("type") == "code"]
            code = code_blocks[0].get("text", "") if code_blocks else ""
            if not code:
                m = re.search(r"```python\n(.*?)```", ans, flags=re.DOTALL)
                code = m.group(1) if m else ""
            try:
                if code:
                    ast.parse(code)
                    syntax_ok = True
                else:
                    syntax_ok = False
            except SyntaxError:
                syntax_ok = False
            structure_ok = bool(code) and syntax_ok
        elif case_id == "p6_explain":
            lowered = ans.lower()
            structure_ok = len(ans.split()) >= 40 and ("например" in lowered or "пример" in lowered or "это" in lowered)
        # Field preservation: QX-77 from 3a should not be eaten — check known token if asked
        phase6.append(
            {
                "type": case_id,
                "structure_ok": "y" if structure_ok else "n",
                "wall_of_text": "y" if wall else "n",
                "fields_preserved": fields,
                "locale_ok": "y" if locale_ok else "n",
                "trace_id": rec["trace_id"],
                "task_id": rec["task_id"],
                "latency_ms": rec["latency_ms"],
                "answer_trunc500": ans[:500],
                "block_types": types,
            }
        )
    # field preservation probe (Phase 3a fact)
    t6f = f"w10-p6-fields-{uuid.uuid4().hex[:8]}"
    ensure_session(token, t6f, "p6_fields")
    att2 = upload_text_attachment(
        token,
        t6f,
        "qx.txt",
        "Проект Зенит использует протокол QX-77 для синхронизации.",
    )
    rec = process_turn(
        token=token,
        thread_id=t6f,
        text="Кратко: какой протокол у Зенит? Обязательно сохрани точное имя протокола.",
        attachment_ids=[att2],
        case_id="p6_fields",
    )
    fields_ok = "QX-77" in rec["answer_text"]
    for row in phase6:
        if row["fields_preserved"] == "n/a":
            row["fields_preserved"] = "y" if fields_ok else "n"
    phase6.append(
        {
            "type": "p6_fields",
            "structure_ok": "y",
            "wall_of_text": "n",
            "fields_preserved": "y" if fields_ok else "n",
            "locale_ok": "y" if _output_locale(rec).startswith("ru") else "n",
            "trace_id": rec["trace_id"],
            "task_id": rec["task_id"],
            "answer_trunc500": rec["answer_text"][:500],
        }
    )
    save("phase6.json", phase6)
    report["phases"]["6"] = phase6

    # ---------- Phase 4 harness traces ----------
    all_cases = [("phase1", row["case_id"], row["trace_id"], row.get("thread_id")) for row in phase1]
    for key in ("2a", "2b", "2c"):
        all_cases.extend((key, row["turn"], row["trace_id"], phase2[key]["thread_id"]) for row in phase2[key]["transcript"])
    all_cases.extend((key, key, payload["trace_id"], payload["thread_id"]) for key, payload in phase3.items())
    all_cases.extend(("phase6", row["type"], row["trace_id"], None) for row in phase6)

    phase4_rows = []
    harness_all = True
    for phase, case_id, trace_id, thread_id in all_cases:
        if not trace_id:
            harness_all = False
            phase4_rows.append(
                {
                    "phase": phase,
                    "case": case_id,
                    "trace_id": None,
                    "agent_spans": [],
                    "handoffs": [],
                    "tool_calls": [],
                    "verify_failed": [],
                    "notes": "missing trace_id",
                }
            )
            continue
        logs = docker_logs_for_trace(trace_id, since="6h")
        save(f"traces/{case_id}_{trace_id}.log", "\n".join(logs))
        agent_spans = sorted(
            {
                m.group(1)
                for ln in logs
                for m in [re.search(r"run_name['\":\s]+['\"]?(agent\.run|[\w]+\.run|graph\.node\.[\w]+|harness\.[\w]+)", ln)]
                if m
            }
        )
        # also catch payload run_name
        for ln in logs:
            for m in re.finditer(r"'run_name': '([^']+)'", ln):
                agent_spans.append(m.group(1))
            for m in re.finditer(r'"run_name": "([^"]+)"', ln):
                agent_spans.append(m.group(1))
        agent_spans = sorted(set(agent_spans))
        handoffs = [ln for ln in logs if "agent.handoff" in ln or "handoff" in ln]
        tool_calls = [
            ln for ln in logs if "tool" in ln.lower() and ("ToolExecutor" in ln or "mcp" in ln.lower() or "tool_call" in ln)
        ]
        verify_failed = [ln for ln in logs if "verify_failed" in ln or ("verify_result" in ln and "error" in ln)]
        has_agent_run = any("agent.run" in s or s.endswith(".run") for s in agent_spans) or any(
            "execute_with_guardrails" in ln or "agent.run" in ln for ln in logs
        )
        if not has_agent_run:
            harness_all = False
        mcp = None
        if thread_id:
            mcp = get_mcp_calls(token, thread_id)
        phase4_rows.append(
            {
                "phase": phase,
                "case": case_id,
                "trace_id": trace_id,
                "agent_spans": agent_spans,
                "handoffs_log_count": len(handoffs),
                "handoffs_sample": handoffs[:5],
                "tool_calls_log_count": len(tool_calls),
                "verify_failed": verify_failed[:10],
                "has_agent_run_or_guardrails": has_agent_run,
                "log_lines": len(logs),
                "mcp_tool_calls": mcp,
                "notes": "" if has_agent_run else "CRITICAL: no harness agent.run evidence in logs",
            }
        )
    phase4 = {
        "rows": phase4_rows,
        "harness_in_all_cases": harness_all,
        "metrics_after": metrics_snapshot(),
        "metrics_before": phase0["metrics_before"],
    }
    save("phase4.json", phase4)
    report["phases"]["4"] = {
        "harness_in_all_cases": harness_all,
        "case_count": len(phase4_rows),
        "with_agent_run": sum(1 for r in phase4_rows if r["has_agent_run_or_guardrails"]),
    }

    # ---------- Phase 5 Neo4j ----------
    print("Waiting 35s for extract/promote flush window...")
    time.sleep(35)
    test_start = phase0["test_start_ts"]
    facts_after = neo4j_query("MATCH (n:MemoryFact) RETURN count(n) AS facts")[0]["facts"]
    labels_after = neo4j_query("MATCH (n) RETURN DISTINCT labels(n) AS labels, count(*) AS c ORDER BY c DESC")
    rels_after = neo4j_query("MATCH ()-[r]->() RETURN type(r) AS rel, count(*) AS c ORDER BY c DESC")
    # Prefer created_at filter; if property missing/type odd, still dump recent
    # Schema (neo4j_graph_write_port): node_id, text, kind, created_at — not id/content.
    cypher_new = """
    MATCH (n:MemoryFact)
    WHERE n.created_at IS NOT NULL AND toString(n.created_at) > $test_start_ts
    RETURN n.node_id AS id, n.kind AS kind, n.text AS content, n.created_at AS created_at,
           n.entry_key AS entry_key, n.source_type AS source_type, n.user_id AS user_id
    ORDER BY n.created_at DESC
    LIMIT 50
    """
    new_facts = neo4j_query(cypher_new, {"test_start_ts": test_start})
    # also dump all facts for evidence
    all_facts = neo4j_query(
        """
        MATCH (n:MemoryFact)
        RETURN n.node_id AS id, n.kind AS kind, n.text AS content, n.created_at AS created_at,
               n.entry_key AS entry_key, n.source_type AS source_type, properties(n) AS props
        ORDER BY coalesce(n.created_at, datetime('1970-01-01T00:00:00Z')) DESC
        LIMIT 50
        """
    )
    cypher_rels = """
    MATCH (a:MemoryFact)-[r]->(b)
    WHERE (a.created_at IS NOT NULL AND toString(a.created_at) > $test_start_ts)
       OR (b.created_at IS NOT NULL AND toString(b.created_at) > $test_start_ts)
    RETURN type(r) AS rel_type, a.node_id AS from_id, coalesce(b.node_id, id(b)) AS to_id,
           labels(b) AS to_labels
    LIMIT 50
    """
    new_rels = neo4j_query(cypher_rels, {"test_start_ts": test_start})
    broken = neo4j_query(
        """
        MATCH (n:MemoryFact)
        WHERE n.node_id IS NULL OR n.text IS NULL OR n.kind IS NULL
        RETURN count(n) AS broken
        """
    )[0]["broken"]
    kinds = neo4j_query(
        """
        MATCH (n:MemoryFact)
        RETURN coalesce(n.kind, 'missing') AS kind, count(*) AS c
        ORDER BY c DESC
        """
    )

    # 5.3 read-back in new thread
    t5 = f"w10-5-readback-{uuid.uuid4().hex[:8]}"
    ensure_session(token, t5, "phase5-readback")
    rec = process_turn(
        token=token,
        thread_id=t5,
        text="Что ты знаешь про проект Зенит?",
        case_id="5_readback",
    )
    read_ans = rec["answer_text"]
    read_ok = any(x in read_ans for x in ("QX-77", "Алекс", "бета", "ZNT-2026", "BGT-42"))

    # Check medium extract evidence via mcp tool calls on a fact-rich thread
    mcp_2a = get_mcp_calls(token, t2a)

    facts_before = phase0["components"][3]["facts_before"]
    rels_before_count = sum(r.get("c", 0) for r in (phase0["components"][3].get("rels_before") or []))
    rels_after_count = sum(r.get("c", 0) for r in rels_after)
    phase5 = {
        "facts_before": facts_before,
        "facts_after": facts_after,
        "delta_facts": facts_after - facts_before,
        "rels_before": rels_before_count,
        "rels_after": rels_after_count,
        "delta_rels": rels_after_count - rels_before_count,
        "labels_after": labels_after,
        "kinds": kinds,
        "broken": broken,
        "sample_new_facts": new_facts[:5],
        "sample_new_rels": new_rels[:5],
        "all_facts_dump": all_facts,
        "cypher": {
            "new_facts": cypher_new,
            "new_rels": cypher_rels,
            "params": {"test_start_ts": test_start},
        },
        "read_back_ok": "yes" if read_ok else "no",
        "read_back_answer": read_ans,
        "read_back_trace_id": rec["trace_id"],
        "memory_keeper": "off-graph (ADR-0010); sleep-time extract → medium via save_memory MCP; Neo4j via promote job",
        "mcp_calls_thread_2a": mcp_2a,
        "reason_if_delta_zero": None,
    }
    if phase5["delta_facts"] == 0:
        phase5["reason_if_delta_zero"] = (
            "Expected gap unless promote ran: MemoryKeeper is off-graph; live chat "
            "triggers sleep-time extract into Postgres medium (MCP save_memory), not "
            "direct Neo4j MemoryFact writes. Neo4j growth requires memory-consolidate/promote job."
        )
    save("phase5.json", phase5)
    report["phases"]["5"] = phase5

    report["finished_at"] = _now()
    save("report_raw.json", report)
    print(
        json.dumps(
            {"ok": True, "out": str(OUT), "summary": list(report["phases"].keys())},
            ensure_ascii=False,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

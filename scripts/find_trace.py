"""Find one turn by trace-id prefix in the local LangGraph checkpointer.

Usage::

    uv run python scripts/find_trace.py cd0f2fed
"""

from __future__ import annotations

import sys

from langgraph.checkpoint.postgres import PostgresSaver

CONN = "postgresql://postgres:1234@localhost:5434/postgres"


def main(argv: list[str]) -> int:
    if not argv:
        print("usage: find_trace.py <trace-id-prefix>")
        return 2
    prefix = argv[0]
    found = 0
    with PostgresSaver.from_conn_string(CONN) as saver:
        for item in saver.list(None, limit=3000):
            values = item.checkpoint.get("channel_values", {})
            trace_id = str(values.get("trace_id") or "")
            if not trace_id.startswith(prefix):
                continue
            found += 1
            execution = values.get("execution")
            formatted = values.get("formatted")
            summary = getattr(getattr(execution, "output", None), "summary", None)
            document = getattr(formatted, "output", None)
            print(
                f"trace={trace_id} thread={values.get('thread_id')} "
                f"task={values.get('task_id')} step={item.metadata.get('step')} "
                f"summary={len(summary) if summary else 0}c "
                f"blocks={len(document.blocks) if document else 0}"
            )
            if summary and document:
                print("worker:", summary[:400].replace("\n", " "))
                print("title:", document.title)
            elif document:
                print(
                    f"exec_type={type(execution).__name__} "
                    f"output_type={type(getattr(execution, 'output', None)).__name__} "
                    f"fmt_type={type(formatted).__name__} "
                    f"fmt_task={getattr(formatted, 'task_id', None)} "
                    f"title={document.title!r}"
                )
    print(f"matches: {found}")
    return 0 if found else 1


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))

# src/palatium_ai/infrastructure/analysis/local_dataframe_analysis.py

"""Local ADA-style analysis for CSV/XLSX attachments (G15) — no network egress.

Runs deterministic pandas summaries inside ``asyncio.to_thread``. Arbitrary code
execution is intentionally out of scope: ChatGPT ADA parity for *live* sandbox
needs an isolated runtime + HITL (020); this adapter is the safe first live path
so Analyst/HITL can reason over tabular attachments without a stub-only refuse.
"""

from __future__ import annotations

import asyncio
import csv
import io
import json

from typing import Any

import structlog

from palatium_ai.domain.ports.attachment_analysis import (
    AttachmentAnalysisRequest,
    AttachmentAnalysisResult,
)

logger = structlog.get_logger(__name__)

_CSV_MIMES = frozenset({"text/csv", "text/plain"})
_XLSX_MIME = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
_MAX_SAMPLE_ROWS = 20
_MAX_COLUMNS = 64
_MAX_SHEETS = 8


class LocalDataframeAttachmentAnalysis:
    """Summarize owned tabular blobs without shell/network (fail closed on other MIME)."""

    async def analyze(self, request: AttachmentAnalysisRequest) -> AttachmentAnalysisResult:
        """Load CSV/XLSX bytes and return structured tables + plain summary."""
        mime = (request.mime_type or "").strip().lower()
        if (
            mime not in _CSV_MIMES
            and mime != _XLSX_MIME
            and not request.filename.lower().endswith((".csv", ".xlsx", ".txt"))
        ):
            msg = f"local analysis supports CSV/XLSX only; got {mime or 'unknown'}"
            raise RuntimeError(msg)

        return await asyncio.to_thread(self._analyze_sync, request)

    def _analyze_sync(self, request: AttachmentAnalysisRequest) -> AttachmentAnalysisResult:
        name = request.filename.lower()
        if name.endswith(".xlsx") or request.mime_type == _XLSX_MIME:
            tables = self._from_xlsx(request.data)
        else:
            tables = [self._from_csv(request.data, sheet="sheet1")]

        summary_parts = [
            f"Analyzed attachment {request.attachment_id} ({request.filename}).",
            f"Instruction: {request.instruction.strip()[:500]}",
            f"Sheets/tables: {len(tables)}.",
        ]
        summary_parts.extend(
            (
                f"- {table['name']}: {table['row_count']} rows × {len(table['columns'])} cols "
                f"[{', '.join(table['columns'][:12])}{'…' if len(table['columns']) > 12 else ''}]"
            )
            for table in tables
        )
        return AttachmentAnalysisResult(
            summary="\n".join(summary_parts)[:8_000],
            tables_json=json.dumps(tables, ensure_ascii=False)[:100_000],
            charts_json="[]",
        )

    def _from_csv(self, data: bytes, *, sheet: str) -> dict[str, Any]:
        text = data.decode("utf-8-sig", errors="replace")
        reader = csv.reader(io.StringIO(text))
        rows = list(reader)
        if not rows:
            return {"name": sheet, "columns": [], "row_count": 0, "sample": [], "dtypes": {}}
        header = [str(cell)[:128] for cell in rows[0][:_MAX_COLUMNS]]
        body = rows[1:]
        sample = [[str(cell)[:256] for cell in row[: len(header)]] for row in body[:_MAX_SAMPLE_ROWS]]
        return {
            "name": sheet,
            "columns": header,
            "row_count": len(body),
            "sample": sample,
            "dtypes": {col: "string" for col in header},
        }

    def _from_xlsx(self, data: bytes) -> list[dict[str, Any]]:
        try:
            from openpyxl import load_workbook
        except ImportError as exc:
            msg = "openpyxl is required for XLSX analysis; install attachments extras"
            raise RuntimeError(msg) from exc

        workbook = load_workbook(io.BytesIO(data), read_only=True, data_only=True)
        tables: list[dict[str, Any]] = []
        try:
            for sheet_name in workbook.sheetnames[:_MAX_SHEETS]:
                worksheet = workbook[sheet_name]
                rows_iter = worksheet.iter_rows(values_only=True)
                try:
                    first = next(rows_iter)
                except StopIteration:
                    tables.append(
                        {"name": sheet_name, "columns": [], "row_count": 0, "sample": [], "dtypes": {}},
                    )
                    continue
                header = [str(cell if cell is not None else "")[:128] for cell in first[:_MAX_COLUMNS]]
                body: list[list[str]] = []
                sample: list[list[str]] = []
                for row in rows_iter:
                    body.append([])
                    cells = [str(cell if cell is not None else "")[:256] for cell in row[: len(header)]]
                    if len(sample) < _MAX_SAMPLE_ROWS:
                        sample.append(cells)
                tables.append(
                    {
                        "name": sheet_name,
                        "columns": header,
                        "row_count": len(body),
                        "sample": sample,
                        "dtypes": {col: "string" for col in header},
                    },
                )
        finally:
            workbook.close()
        return tables


__all__ = ["LocalDataframeAttachmentAnalysis"]

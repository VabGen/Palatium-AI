# tests/unit/test_local_dataframe_analysis.py

"""Local ADA tabular analysis (G15)."""

from __future__ import annotations

import json

from uuid import uuid4

import pytest

from palatium_ai.domain.ports.attachment_analysis import AttachmentAnalysisRequest
from palatium_ai.infrastructure.analysis.local_dataframe_analysis import (
    LocalDataframeAttachmentAnalysis,
)


@pytest.mark.asyncio()
async def test_local_analysis_summarizes_csv() -> None:
    csv_bytes = b"name,amount\nalice,10\nbob,20\n"
    result = await LocalDataframeAttachmentAnalysis().analyze(
        AttachmentAnalysisRequest(
            attachment_id=uuid4(),
            user_id="u1",
            instruction="Summarize spend by person",
            filename="spend.csv",
            mime_type="text/csv",
            data=csv_bytes,
        ),
    )
    assert "spend.csv" in result.summary
    tables = json.loads(result.tables_json)
    assert tables[0]["columns"] == ["name", "amount"]
    assert tables[0]["row_count"] == 2


@pytest.mark.asyncio()
async def test_local_analysis_refuses_non_tabular() -> None:
    with pytest.raises(RuntimeError, match="CSV/XLSX"):
        await LocalDataframeAttachmentAnalysis().analyze(
            AttachmentAnalysisRequest(
                attachment_id=uuid4(),
                user_id="u1",
                instruction="Describe",
                filename="scan.pdf",
                mime_type="application/pdf",
                data=b"%PDF",
            ),
        )

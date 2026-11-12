# src/palatium_ai/application/agents/formatter/layout_coercion.py

"""Repair layout slips that JSON Schema cannot express (tables / charts).

Cross-field invariants (row width == columns, series length == labels) live outside
the provider's schema. Without a coerce step, a single ragged row rejects the whole
``ContentDocument`` after the stream already painted valid blocks — the Formatter
then restarts on the legacy Markdown path and the UI snaps from one surface to
another (040: ``layout_shift_count``). Pad / truncate here so progressive
``block_delta`` and the final document stay the same contract.
"""

from __future__ import annotations


def coerce_layout_fields(node: object) -> tuple[object, int]:
    """Align table rows and chart series to their declared widths; return ``(node, fixes)``."""
    if isinstance(node, dict):
        block_type = node.get("type")
        if block_type == "table":
            return _coerce_table(node)
        if block_type == "chart":
            return _coerce_chart(node)
        fixed = 0
        cleaned: dict[str, object] = {}
        for key, value in node.items():
            nested, lost = coerce_layout_fields(value)
            cleaned[key] = nested
            fixed += lost
        return cleaned, fixed
    if isinstance(node, list):
        items: list[object] = []
        fixed = 0
        for item in node:
            nested, lost = coerce_layout_fields(item)
            items.append(nested)
            fixed += lost
        return items, fixed
    return node, 0


def _coerce_table(node: dict[str, object]) -> tuple[dict[str, object], int]:
    columns = node.get("columns")
    rows = node.get("rows")
    if not isinstance(columns, list) or not isinstance(rows, list):
        return node, 0
    width = len(columns)
    if width == 0:
        return node, 0
    fixed = 0
    next_rows: list[object] = []
    for row in rows:
        if not isinstance(row, list):
            next_rows.append(row)
            continue
        cells = [_cell_text(cell) for cell in row]
        if len(cells) == width:
            next_rows.append(cells)
            continue
        fixed += 1
        if len(cells) < width:
            next_rows.append([*cells, *([""] * (width - len(cells)))])
        else:
            next_rows.append(cells[:width])
    if fixed == 0:
        return node, 0
    return {**node, "rows": next_rows}, fixed


def _coerce_chart(node: dict[str, object]) -> tuple[dict[str, object], int]:
    labels = node.get("labels")
    series = node.get("series")
    if not isinstance(labels, list) or not isinstance(series, list):
        return node, 0
    width = len(labels)
    fixed = 0
    next_series: list[object] = []
    for entry in series:
        if not isinstance(entry, dict):
            next_series.append(entry)
            continue
        values = entry.get("values")
        if not isinstance(values, list) or len(values) == width:
            next_series.append(entry)
            continue
        fixed += 1
        nums = [_num(v) for v in values]
        aligned = [*nums, *([0.0] * (width - len(nums)))] if len(nums) < width else nums[:width]
        next_series.append({**entry, "values": aligned})
    if fixed == 0:
        return node, 0
    return {**node, "series": next_series}, fixed


def _cell_text(value: object) -> str:
    if value is None:
        return ""
    if isinstance(value, str):
        return value
    return str(value)


def _num(value: object) -> float:
    if isinstance(value, bool):
        return float(value)
    if isinstance(value, int | float):
        return float(value)
    try:
        return float(str(value))
    except TypeError, ValueError:
        return 0.0


__all__ = ["coerce_layout_fields"]

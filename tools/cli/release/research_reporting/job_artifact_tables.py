"""Safe preview decoding for Job report artifacts.

The report tree owns a small, immediately readable preview. The complete
artifact remains in the global Job cache and is opened on demand by clients.
"""

from __future__ import annotations

import csv
import io
import json
from typing import Any


MAX_PREVIEW_ROWS = 200
MAX_PREVIEW_COLUMNS = 20
MAX_CELL_CHARACTERS = 2048


def table_content(
    raw: bytes, content_type: str, *, source: dict[str, str],
) -> dict[str, Any]:
    """Return a bounded preview and an immutable pointer to its full artifact."""
    if content_type == "text/csv":
        reader = csv.reader(io.StringIO(raw.decode("utf-8-sig")))
        try:
            original_columns = next(reader)
        except StopIteration:
            raise ValueError("CSV 为空")
        values: Any = reader
    else:
        original_columns, values = json_rows(json.loads(raw.decode("utf-8")))
    if not isinstance(original_columns, list) or not original_columns:
        raise ValueError("统计表缺少列")
    columns = [str(item)[:256] for item in original_columns[:MAX_PREVIEW_COLUMNS]]
    width = len(columns)
    iterator = iter(values)
    normalized: list[list[str]] = []
    for _ in range(MAX_PREVIEW_ROWS):
        try:
            row = next(iterator)
        except StopIteration:
            break
        if isinstance(row, dict):
            row = [row.get(column, "") for column in columns]
        if not isinstance(row, list):
            raise ValueError("统计表行格式无效")
        normalized.append(
            [str(item)[:MAX_CELL_CHARACTERS] for item in row[:width]]
            + [""] * max(0, width - len(row))
        )
    has_more_rows = next(iterator, None) is not None
    return {
        "columns": columns,
        "rows": normalized,
        "preview": {
            "max_rows": MAX_PREVIEW_ROWS,
            "max_columns": MAX_PREVIEW_COLUMNS,
            "is_truncated": has_more_rows
            or len(original_columns) > MAX_PREVIEW_COLUMNS,
        },
        "source": source,
    }


def json_rows(value: Any) -> tuple[list[str], list[list[Any]]]:
    if isinstance(value, dict) and isinstance(value.get("columns"), list) and isinstance(value.get("rows"), list):
        return list(value["columns"]), list(value["rows"])
    if isinstance(value, dict) and isinstance(value.get("rows"), list):
        return json_rows(value["rows"])
    if isinstance(value, list) and value and all(isinstance(item, dict) for item in value):
        columns = list(dict.fromkeys(str(key) for item in value for key in item))
        return columns, [[item.get(column, "") for column in columns] for item in value]
    if isinstance(value, dict):
        return ["key", "value"], [[key, item] for key, item in value.items()]
    if isinstance(value, list):
        return ["value"], [[item] for item in value]
    return ["value"], [[value]]

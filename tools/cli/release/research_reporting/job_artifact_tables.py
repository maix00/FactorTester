"""Safe bounded table decoding for Job report artifacts."""

from __future__ import annotations

import csv
import io
import json
from typing import Any


MAX_TABLE_ROWS = 4096
MAX_TABLE_COLUMNS = 32


def table_content(raw: bytes, content_type: str) -> dict[str, Any]:
    if content_type == "text/csv":
        rows = list(csv.reader(io.StringIO(raw.decode("utf-8-sig"))))
        if not rows:
            raise ValueError("CSV 为空")
        columns, values = rows[0], rows[1:]
    else:
        columns, values = json_rows(json.loads(raw.decode("utf-8")))
    if not isinstance(columns, list) or not columns:
        raise ValueError("统计表缺少列")
    columns = [str(item)[:256] for item in columns[:MAX_TABLE_COLUMNS]]
    width = len(columns)
    normalized = []
    for row in values[:MAX_TABLE_ROWS]:
        if isinstance(row, dict):
            row = [row.get(column, "") for column in columns]
        if not isinstance(row, list):
            raise ValueError("统计表行格式无效")
        normalized.append([str(item)[:2048] for item in row[:width]] + [""] * max(0, width - len(row)))
    return {"columns": columns, "rows": normalized}


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

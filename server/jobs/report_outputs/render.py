"""Deterministic JSON, CSV and compact SVG encoders."""

from __future__ import annotations

import csv
import io
import json
from typing import Any


def json_bytes(value: Any) -> bytes:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, default=str, separators=(",", ":")).encode("utf-8")


def csv_bytes(rows: list[dict[str, Any]]) -> bytes:
    columns = sorted({key for row in rows for key in row if key != "raw"})
    output = io.StringIO()
    writer = csv.DictWriter(output, fieldnames=columns or ["empty"])
    writer.writeheader()
    for row in rows:
        writer.writerow({key: row.get(key) for key in writer.fieldnames})
    return output.getvalue().encode("utf-8-sig")

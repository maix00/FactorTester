"""Deterministic JSON, CSV and compact SVG encoders."""

from __future__ import annotations

import csv
import io
import json
from typing import Any


def json_bytes(value: Any) -> bytes:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, default=str, separators=(",", ":")).encode("utf-8")


def csv_bytes(
    rows: list[dict[str, Any]], *, columns: list[str] | None = None,
) -> bytes:
    """Encode rows as UTF-8 CSV, optionally preserving a curated column order.

    Raw diagnostic tables keep their historical deterministic sorted-column
    layout.  Report-facing summary tables pass an explicit order so the
    rendered artifact is stable and readable without changing the raw table.
    """
    if columns is None:
        columns = sorted({key for row in rows for key in row if key != "raw"})
    else:
        columns = [str(column) for column in columns if str(column) != "raw"]
    output = io.StringIO()
    writer = csv.DictWriter(output, fieldnames=columns or ["empty"])
    writer.writeheader()
    for row in rows:
        writer.writerow({key: row.get(key) for key in writer.fieldnames})
    return output.getvalue().encode("utf-8-sig")

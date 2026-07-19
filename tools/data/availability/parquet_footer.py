"""Low-cost Parquet coverage inspection using metadata only."""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import pandas as pd
import pyarrow.parquet as pq

from .model import canonical_hash, utc_iso


def inspect_parquet(
    path_value: str | Path,
    *,
    time_columns: tuple[str, ...],
    source_key: str,
    product_name: str,
    frequency: str,
) -> dict[str, Any]:
    path = Path(path_value)
    if not path.is_file() or path.stat().st_size <= 0:
        return {"status": "unavailable", "reason": "file_missing_or_empty"}

    parquet = pq.ParquetFile(path)
    if parquet.metadata.num_rows <= 0:
        return {"status": "unavailable", "reason": "file_has_no_rows"}

    start, end = _footer_bounds(parquet, time_columns)
    stat = path.stat()
    updated_at = utc_iso(datetime.fromtimestamp(stat.st_mtime, tz=timezone.utc))
    identity = {
        "source": source_key,
        "product": product_name,
        "frequency": frequency,
        "size": stat.st_size,
        "mtime_ns": stat.st_mtime_ns,
        "rows": parquet.metadata.num_rows,
    }
    coverage = {
        "start": _timestamp_text(start),
        "end": _timestamp_text(end),
        "assurance": (
            "parquet_footer_statistics"
            if start is not None and end is not None
            else "unknown_without_data_scan"
        ),
    }
    return {
        "status": "available",
        "coverage": coverage,
        "updated_at": updated_at,
        "snapshot_ref": f"filemeta:{canonical_hash(identity)}",
    }


def _footer_bounds(
    parquet: pq.ParquetFile,
    time_columns: tuple[str, ...],
) -> tuple[Any | None, Any | None]:
    column_names = parquet.schema_arrow.names
    for name in time_columns:
        if name not in column_names:
            continue
        index = column_names.index(name)
        minima: list[Any] = []
        maxima: list[Any] = []
        for group_index in range(parquet.num_row_groups):
            statistics = parquet.metadata.row_group(group_index).column(index).statistics
            if statistics is None or not statistics.has_min_max:
                return None, None
            if statistics.min is not None:
                minima.append(statistics.min)
            if statistics.max is not None:
                maxima.append(statistics.max)
        if minima and maxima:
            return min(minima), max(maxima)
    return None, None


def _timestamp_text(value: Any | None) -> str | None:
    if value is None:
        return None
    timestamp = pd.Timestamp(value)
    return timestamp.isoformat()

"""Immutable helpers for narrow product time-series reads."""
from __future__ import annotations

from hashlib import sha256
from functools import lru_cache
import json
import os
from typing import Any, Iterable, Mapping, Sequence


def raw_columns_for(
    *,
    time_mapping: Mapping[Any, Any],
    data_mapping: Mapping[Any, Any],
    canonical_columns: Iterable[str],
    available_columns: Iterable[str] | None = None,
) -> tuple[str, ...]:
    """Resolve canonical columns to the raw columns required by a source."""
    wanted = {str(column) for column in canonical_columns}
    raw_time = [str(column) for column in time_mapping]
    raw_data = [
        str(raw)
        for raw, canonical in data_mapping.items()
        if str(canonical) in wanted
    ]
    resolved = tuple(dict.fromkeys([*raw_time, *raw_data]))
    if available_columns is None:
        return resolved
    available = set(available_columns)
    return tuple(column for column in resolved if column in available)


def available_raw_columns(path: str) -> frozenset[str] | None:
    """Read only source metadata and cache it by immutable file revision."""
    try:
        stat = os.stat(path)
    except OSError:
        return None
    return _available_raw_columns(path, stat.st_mtime_ns, stat.st_size)


@lru_cache(maxsize=1024)
def _available_raw_columns(path: str, _mtime_ns: int, _size: int) -> frozenset[str] | None:
    lower = path.lower()
    if lower.endswith(".parquet"):
        import pyarrow.parquet as parquet

        return frozenset(str(name) for name in parquet.ParquetFile(path).schema_arrow.names)
    if lower.endswith(".csv"):
        import pandas as pd

        return frozenset(str(name) for name in pd.read_csv(path, nrows=0).columns)
    if lower.endswith(".xlsx"):
        import pandas as pd

        return frozenset(str(name) for name in pd.read_excel(path, nrows=0).columns)
    return None


def read_cache_key(
    *,
    base_key: str,
    path: str,
    raw_columns: Sequence[str],
    filters: Sequence[tuple[str, str, Any]],
) -> str:
    """Isolate cached scans by file revision, selected columns, and row window."""
    try:
        stat = os.stat(path)
        revision = f"{stat.st_mtime_ns}:{stat.st_size}"
    except OSError:
        revision = "missing"
    payload = {
        "revision": revision,
        "columns": list(raw_columns),
        "filters": [
            [column, operator, value.isoformat() if hasattr(value, "isoformat") else str(value)]
            for column, operator, value in filters
        ],
    }
    digest = sha256(
        json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
    ).hexdigest()
    return f"{base_key}:projection:{digest}"

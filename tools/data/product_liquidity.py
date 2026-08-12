"""Exact point-in-time liquidity summaries from local DAY1 volume files."""

from __future__ import annotations

from functools import lru_cache
import re
from pathlib import Path
from typing import Any

import pandas as pd


def summarize_day1_volume_batch(
    *,
    product_paths: dict[str, str | None],
    day_column: str,
    volume_column: str,
    as_of: str,
    window_days: int,
) -> list[dict[str, Any]]:
    """Scan all valid files once and return deterministic per-product summaries."""
    cutoff = _date(as_of, field="as_of")
    if not isinstance(window_days, int) or isinstance(window_days, bool) or window_days < 1:
        raise ValueError("window_days must be a positive integer")
    if not product_paths:
        raise ValueError("product_paths must not be empty")
    requested_start = cutoff - pd.Timedelta(days=window_days - 1)

    gaps: dict[str, str] = {}
    signatures: list[tuple[str, str, int, int]] = []
    seen_paths: set[str] = set()
    for product in sorted(product_paths):
        raw_path = product_paths[product]
        if not isinstance(raw_path, str) or not raw_path.strip():
            gaps[product] = "source_path_unresolved"
            continue
        path = Path(raw_path).expanduser().resolve()
        if str(path) in seen_paths:
            gaps[product] = "duplicate_source_path"
            continue
        seen_paths.add(str(path))
        if not path.is_file():
            gaps[product] = "source_file_missing"
            continue
        if path.suffix.lower() != ".parquet":
            gaps[product] = "source_file_not_parquet"
            continue
        stat = path.stat()
        signatures.append((product, str(path), stat.st_size, stat.st_mtime_ns))

    rows, scan_gaps = _cached_batch_scan(
        tuple(signatures),
        str(day_column),
        str(volume_column),
        cutoff.strftime("%Y-%m-%d"),
        int(window_days),
    )
    gaps.update(scan_gaps)
    by_product: dict[str, list[tuple[pd.Timestamp, float]]] = {}
    for product, day_text, volume in rows:
        by_product.setdefault(product, []).append((pd.Timestamp(day_text), volume))

    entries: list[dict[str, Any]] = []
    for product in sorted(product_paths):
        gap = gaps.get(product)
        daily_rows = by_product.get(product, [])
        if gap or not daily_rows:
            entries.append(_gap_entry(
                product,
                gap or "no_observations_in_window",
                requested_start,
                cutoff,
            ))
            continue
        daily = pd.Series(
            [value for _, value in daily_rows],
            index=pd.DatetimeIndex([day for day, _ in daily_rows]),
            dtype=float,
        ).sort_index()
        entries.append({
            "product": product,
            "status": "available",
            "statistics_as_of": daily.index[-1].strftime("%Y-%m-%d"),
            "latest_daily_volume": float(daily.iloc[-1]),
            "average_daily_volume": float(daily.mean()),
            "zero_volume_days": int((daily <= 0).sum()),
            "coverage": _coverage(
                requested_start,
                cutoff,
                start=daily.index[0],
                end=daily.index[-1],
                observed_days=len(daily),
            ),
        })
    return entries


@lru_cache(maxsize=32)
def _cached_batch_scan(
    signatures: tuple[tuple[str, str, int, int], ...],
    day_column: str,
    volume_column: str,
    as_of: str,
    window_days: int,
) -> tuple[tuple[tuple[str, str, float], ...], dict[str, str]]:
    if not signatures:
        return (), {}
    import pyarrow.dataset as ds
    import pyarrow.parquet as pq

    valid: list[tuple[str, str]] = []
    gaps: dict[str, str] = {}
    for product, path, _, _ in signatures:
        try:
            names = set(pq.ParquetFile(path).schema_arrow.names)
        except Exception:
            gaps[product] = "parquet_metadata_unreadable"
            continue
        if day_column not in names:
            gaps[product] = "day_column_missing"
        elif volume_column not in names:
            gaps[product] = "volume_column_missing"
        else:
            valid.append((product, path))
    if not valid:
        return (), gaps

    path_to_product = {str(Path(path).resolve()): product for product, path in valid}
    try:
        table = ds.dataset(
            [path for _, path in valid],
            format="parquet",
        ).scanner(columns=[day_column, volume_column, "__filename"]).to_table()
    except Exception:
        for product, _ in valid:
            gaps[product] = "batch_scan_failed"
        return (), gaps

    frame = table.to_pandas()
    frame[day_column] = pd.to_datetime(frame[day_column], errors="coerce").dt.normalize()
    frame[volume_column] = pd.to_numeric(frame[volume_column], errors="coerce")
    frame["_product"] = frame["__filename"].map(
        lambda value: path_to_product.get(str(Path(str(value)).resolve()))
    )
    cutoff = pd.Timestamp(as_of)
    start = cutoff - pd.Timedelta(days=window_days - 1)
    frame = frame[
        frame["_product"].notna()
        & frame[day_column].notna()
        & frame[volume_column].notna()
        & frame[day_column].between(start, cutoff)
    ]
    daily = (
        frame.groupby(["_product", day_column], sort=True)[volume_column]
        .sum(min_count=1)
        .dropna()
    )
    rows = tuple(
        (str(product), pd.Timestamp(day).strftime("%Y-%m-%d"), float(volume))
        for (product, day), volume in daily.items()
    )
    return rows, gaps


def _gap_entry(
    product: str,
    reason: str,
    requested_start: pd.Timestamp,
    requested_end: pd.Timestamp,
) -> dict[str, Any]:
    return {
        "product": product,
        "status": "capability_gap",
        "gap_reason": reason,
        "statistics_as_of": None,
        "latest_daily_volume": None,
        "average_daily_volume": None,
        "zero_volume_days": None,
        "coverage": _coverage(requested_start, requested_end),
    }


def _coverage(
    requested_start: pd.Timestamp,
    requested_end: pd.Timestamp,
    *,
    start: pd.Timestamp | None = None,
    end: pd.Timestamp | None = None,
    observed_days: int = 0,
) -> dict[str, Any]:
    return {
        "requested_start": requested_start.strftime("%Y-%m-%d"),
        "requested_end": requested_end.strftime("%Y-%m-%d"),
        "start": start.strftime("%Y-%m-%d") if start is not None else None,
        "end": end.strftime("%Y-%m-%d") if end is not None else None,
        "observed_days": int(observed_days),
    }


def _date(value: Any, *, field: str) -> pd.Timestamp:
    if not isinstance(value, str) or re.fullmatch(r"\d{4}-\d{2}-\d{2}", value) is None:
        raise ValueError(f"{field} must be an ISO date in YYYY-MM-DD form")
    try:
        result = pd.Timestamp(value).normalize()
    except Exception as exc:
        raise ValueError(f"{field} must be a valid ISO date") from exc
    if pd.isna(result):
        raise ValueError(f"{field} must be a valid ISO date")
    return result

"""Low-cost Parquet coverage inspection using metadata only."""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import pandas as pd
import pyarrow.parquet as pq

from tools.data.types import DataColumn

from .model import utc_iso


def inspect_parquet(
    path_value: str | Path,
    *,
    time_columns: tuple[str, ...],
    data_columns: dict[str, str] | None = None,
    required_fields: tuple[str, ...] = (),
    include_field_catalog: bool = False,
    time_columns_mapping: dict[str, str] | None = None,
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
    coverage = {
        "start": _timestamp_text(start),
        "end": _timestamp_text(end),
        "assurance": (
            "parquet_footer_statistics"
            if start is not None and end is not None
            else "unknown_without_data_scan"
        ),
    }
    value = {
        "status": "available",
        "coverage": coverage,
        "updated_at": updated_at,
    }
    if required_fields:
        value["required_fields"] = _required_field_availability(
            parquet,
            data_columns=data_columns or {},
            required_fields=required_fields,
        )
    if include_field_catalog:
        value["field_catalog"] = _field_catalog(
            parquet,
            data_columns=data_columns or {},
        )
        schema = {field.name: str(field.type) for field in parquet.schema_arrow}
        value["time_fields"] = [
            {
                "physical_field": physical,
                "frequency": frequency,
                "data_type": schema[physical],
            }
            for physical, frequency in (time_columns_mapping or {}).items()
            if physical in schema
        ]
    return value


def _field_catalog(
    parquet: pq.ParquetFile,
    *,
    data_columns: dict[str, str],
) -> list[dict[str, Any]]:
    schema = {field.name: str(field.type) for field in parquet.schema_arrow}
    physical_by_logical = {
        str(logical): str(physical)
        for physical, logical in data_columns.items()
        if str(physical) in schema
    }
    catalog = [
        {
            "field": logical,
            "status": "direct",
            "physical_fields": [physical],
            "data_type": schema[physical],
        }
        for logical, physical in physical_by_logical.items()
    ]
    mul = physical_by_logical.get(DataColumn.ADJUSTMENT_MUL.name)
    add = physical_by_logical.get(DataColumn.ADJUSTMENT_ADD.name)
    for raw_field in ("OPEN", "HIGH", "LOW", "CLOSE"):
        raw = physical_by_logical.get(raw_field)
        if raw is None:
            continue
        adjusted = f"{raw_field}_ADJUSTED"
        if adjusted in physical_by_logical:
            continue
        if mul is not None and add is not None:
            catalog.append({
                "field": adjusted,
                "status": "derived",
                "physical_fields": [raw, mul, add],
                "data_type": schema[raw],
                "derivation": "price_mul_adjustment_plus_addition",
            })
        else:
            catalog.append({
                "field": adjusted,
                "status": "fallback_unadjusted",
                "physical_fields": [raw],
                "data_type": schema[raw],
                "limitation": "adjustment_fields_missing",
            })
    return sorted(catalog, key=lambda item: str(item["field"]))


def _required_field_availability(
    parquet: pq.ParquetFile,
    *,
    data_columns: dict[str, str],
    required_fields: tuple[str, ...],
) -> list[dict[str, Any]]:
    schema = {field.name: str(field.type) for field in parquet.schema_arrow}
    physical_by_logical = {
        str(logical): str(physical)
        for physical, logical in data_columns.items()
    }
    return [
        _required_field(
            value,
            schema=schema,
            physical_by_logical=physical_by_logical,
        )
        for value in required_fields
    ]


def _required_field(
    value: str,
    *,
    schema: dict[str, str],
    physical_by_logical: dict[str, str],
) -> dict[str, Any]:
    field = DataColumn(value).name
    direct = physical_by_logical.get(field)
    if direct in schema:
        return {
            "field": field,
            "status": "direct",
            "physical_fields": [direct],
            "data_type": schema[direct],
        }
    if field.endswith("_ADJUSTED"):
        raw_field = field.removesuffix("_ADJUSTED")
        raw = physical_by_logical.get(raw_field)
        mul = physical_by_logical.get(DataColumn.ADJUSTMENT_MUL.name)
        add = physical_by_logical.get(DataColumn.ADJUSTMENT_ADD.name)
        if raw in schema and mul in schema and add in schema:
            return {
                "field": field,
                "status": "derived",
                "physical_fields": [raw, mul, add],
                "data_type": schema[raw],
                "derivation": "price_mul_adjustment_plus_addition",
            }
        if raw in schema:
            return {
                "field": field,
                "status": "fallback_unadjusted",
                "physical_fields": [raw],
                "data_type": schema[raw],
                "limitation": "adjustment_fields_missing",
            }
    return {
        "field": field,
        "status": "missing",
        "physical_fields": [],
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

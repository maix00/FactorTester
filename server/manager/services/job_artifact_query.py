"""Bounded projections of retained JSON Job artifacts."""

from __future__ import annotations

from collections import OrderedDict
from datetime import datetime
from math import isfinite
from pathlib import Path
from threading import RLock
from typing import Any

import orjson

from server.jobs.artifacts import resolve_artifact_path
from server.manager.services.job_artifact_catalog import JobArtifactCatalog

MAX_PAGE_SIZE = 200
MAX_POINTS = 2_000
_CACHE_ENTRY_BYTES = 32 * 1024 * 1024
_CACHE_TOTAL_BYTES = 64 * 1024 * 1024
_CACHE: OrderedDict[tuple[str, int, int], object] = OrderedDict()
_CACHE_BYTES = 0
_CACHE_LOCK = RLock()


class JobArtifactQueryService:
    """Read a small UI projection from the Manager that stores an artifact."""

    def __init__(self, state: object) -> None:
        self.state = state

    def query(
        self,
        *,
        job_id: str,
        name: str,
        principal: str,
        request: dict[str, object],
    ) -> dict[str, object]:
        metadata = _artifact_metadata(
            JobArtifactCatalog(self.state).list(
                job_id=job_id, principal=principal,
            ),
            name,
        )
        if metadata is None:
            raise KeyError("artifact was not found")
        content_type = str(metadata.get("content_type") or "").lower()
        if "json" not in content_type:
            raise ValueError("only JSON artifacts support bounded queries")
        path = resolve_artifact_path(str(metadata.get("relative_path") or ""))
        expected_size = int(metadata.get("size_bytes") or 0)
        if expected_size and path.stat().st_size != expected_size:
            raise RuntimeError("artifact size metadata changed after registration")
        return query_artifact_value(_load_json(path), request)


def query_artifact_value(
    value: object, request: dict[str, object],
) -> dict[str, object]:
    mode = str(request.get("mode") or "").strip().lower()
    if mode == "table":
        return _table_query(value, request)
    if mode == "series":
        return _series_query(value, request)
    if mode == "time_rows":
        return _time_rows_query(value, request)
    raise ValueError("artifact query mode must be table, series, or time_rows")


def _artifact_metadata(
    artifacts: list[dict[str, object]], name: str,
) -> dict[str, object] | None:
    target = str(name or "").strip()
    for item in artifacts:
        if str(item.get("state") or "") != "active":
            continue
        if target in {
            str(item.get("name") or ""), str(item.get("file_name") or ""),
        }:
            return item
    return None


def _load_json(path: Path) -> object:
    global _CACHE_BYTES
    stat = path.stat()
    key = (str(path), stat.st_size, stat.st_mtime_ns)
    with _CACHE_LOCK:
        cached = _CACHE.get(key)
        if cached is not None:
            _CACHE.move_to_end(key)
            return cached
    value = orjson.loads(path.read_bytes())
    if stat.st_size > _CACHE_ENTRY_BYTES:
        return value
    with _CACHE_LOCK:
        previous = _CACHE.pop(key, None)
        if previous is not None:
            _CACHE_BYTES -= stat.st_size
        _CACHE[key] = value
        _CACHE.move_to_end(key)
        _CACHE_BYTES += stat.st_size
        while _CACHE and _CACHE_BYTES > _CACHE_TOTAL_BYTES:
            old_key, _ = _CACHE.popitem(last=False)
            _CACHE_BYTES -= old_key[1]
    return value


def _table_query(
    value: object, request: dict[str, object],
) -> dict[str, object]:
    model = _table_model(value)
    source_rows = model["rows"]
    filters = _filter_groups(request.get("filters"))
    rows = [row for row in source_rows if _matches_filters(row, filters)]
    facets = {
        key: sorted({
            candidate
            for row in source_rows
            if _matches_filters(row, filters, exclude=key)
            for candidate in [_first_text(row, fields)]
            if candidate
        })
        for key, fields in _field_groups(request.get("facets")).items()
    }
    distinct = {
        key: _distinct_rows(rows, fields)
        for key, fields in _distinct_groups(request.get("distinct")).items()
    }
    page_size = _bounded_int(request.get("page_size"), 20, 1, MAX_PAGE_SIZE)
    page = _bounded_int(request.get("page"), 1, 1, max(1, (len(rows) + page_size - 1) // page_size))
    start = (page - 1) * page_size
    return {
        "query_mode": "table",
        "artifact_kind": _mapping_value(value, "artifact_kind"),
        "schema_version": _mapping_value(value, "schema_version"),
        "columns": model["columns"],
        "column_presentations": model["column_presentations"],
        "rows": rows[start:start + page_size],
        "facets": facets,
        "distinct": distinct,
        "page": page,
        "page_size": page_size,
        "total": len(rows),
    }


def _series_query(
    value: object, request: dict[str, object],
) -> dict[str, object]:
    if not isinstance(value, dict) or not isinstance(value.get("series"), list):
        raise TypeError("artifact does not contain a series collection")
    lower, upper = _range(request)
    maximum = _bounded_int(request.get("max_points"), 800, 20, MAX_POINTS)
    output = []
    source_points = 0
    visible_points = 0
    for raw_item in value["series"]:
        if not isinstance(raw_item, dict):
            continue
        timestamps = raw_item.get("timestamps")
        if not isinstance(timestamps, list):
            continue
        source_points += len(timestamps)
        visible = [
            index for index, timestamp in enumerate(timestamps)
            if _in_range(timestamp, lower, upper)
        ]
        visible_points += len(visible)
        values = raw_item.get("values")
        values = values if isinstance(values, list) else []
        selected = _sample_indices(visible, values, maximum)
        projected = {
            key: item for key, item in raw_item.items()
            if not isinstance(item, list)
        }
        for key, item in raw_item.items():
            if isinstance(item, list) and len(item) == len(timestamps):
                projected[key] = [item[index] for index in selected]
        projected.setdefault(
            "timestamps", [timestamps[index] for index in selected],
        )
        output.append(projected)
    return {
        "query_mode": "series",
        "artifact_kind": value.get("artifact_kind"),
        "schema_version": value.get("schema_version"),
        "series": output,
        "sampling": {
            "source_points": source_points,
            "visible_points": visible_points,
            "returned_points": sum(
                len(item.get("timestamps") or []) for item in output
            ),
            "max_points_per_series": maximum,
            "from": lower,
            "to": upper,
        },
    }


def _time_rows_query(
    value: object, request: dict[str, object],
) -> dict[str, object]:
    model = _table_model(value)
    lower, upper = _range(request)
    maximum = _bounded_int(request.get("max_points"), 800, 20, MAX_POINTS)
    fields = _fields(request.get("fields"))
    grouped: OrderedDict[str, list[dict[str, object]]] = OrderedDict()
    for row in model["rows"]:
        timestamp = row.get("timestamp")
        if not _in_range(timestamp, lower, upper):
            continue
        group = str(
            row.get("strategy_id") or row.get("strategy")
            or row.get("series") or "__all__"
        )
        grouped.setdefault(group, []).append(row)
    selected_rows: list[dict[str, object]] = []
    visible_rows = 0
    for rows in grouped.values():
        visible_rows += len(rows)
        values = [_first_numeric(row, fields) for row in rows]
        indices = _sample_indices(list(range(len(rows))), values, maximum)
        selected_rows.extend(_project_row(rows[index], fields) for index in indices)
    selected_rows.sort(key=lambda row: (
        _timestamp_number(row.get("timestamp")) or 0,
        str(row.get("strategy_id") or row.get("strategy") or row.get("series") or ""),
    ))
    return {
        "query_mode": "time_rows",
        "artifact_kind": _mapping_value(value, "artifact_kind"),
        "schema_version": _mapping_value(value, "schema_version"),
        "rows": selected_rows,
        "sampling": {
            "source_rows": len(model["rows"]),
            "visible_rows": visible_rows,
            "returned_rows": len(selected_rows),
            "max_points_per_series": maximum,
            "from": lower,
            "to": upper,
        },
    }


def _table_model(value: object) -> dict[str, Any]:
    if isinstance(value, list) and all(isinstance(item, dict) for item in value):
        return {
            "columns": _columns(value), "rows": value,
            "column_presentations": {},
        }
    if not isinstance(value, dict):
        raise TypeError("artifact does not contain tabular rows")
    rows = value.get("rows")
    columns = value.get("columns")
    if isinstance(rows, list) and all(isinstance(item, dict) for item in rows):
        preferred = [str(item) for item in columns] if isinstance(columns, list) else []
        presentations = value.get("column_presentations")
        return {
            "columns": preferred or _columns(rows),
            "rows": rows,
            "column_presentations": presentations if isinstance(presentations, dict) else {},
        }
    for item in value.values():
        try:
            return _table_model(item)
        except (TypeError, ValueError):
            continue
    raise ValueError("artifact does not contain tabular rows")


def _columns(rows: list[dict[str, object]]) -> list[str]:
    return list(dict.fromkeys(
        key for row in rows[:500] for key in row
    ))


def _field_groups(value: object) -> dict[str, list[str]]:
    if value is None:
        return {}
    if not isinstance(value, dict) or len(value) > 16:
        raise ValueError("artifact query facets must be an object of at most 16 groups")
    return {
        str(key): _field_names(fields)
        for key, fields in value.items()
    }


def _filter_groups(value: object) -> dict[str, dict[str, object]]:
    if value is None:
        return {}
    if not isinstance(value, dict) or len(value) > 16:
        raise ValueError("artifact query filters must be an object of at most 16 groups")
    output = {}
    for key, definition in value.items():
        if not isinstance(definition, dict):
            raise TypeError("artifact query filter must be an object")
        values = definition.get("values")
        if not isinstance(values, list) or len(values) > 256:
            raise ValueError("artifact query filter values must be a bounded array")
        output[str(key)] = {
            "fields": _field_names(definition.get("fields")),
            "values": {str(item) for item in values},
        }
    return output


def _distinct_groups(value: object) -> dict[str, dict[str, list[str]]]:
    if value is None:
        return {}
    if not isinstance(value, dict) or len(value) > 8:
        raise ValueError("artifact query distinct groups must be a bounded object")
    output = {}
    for key, definition in value.items():
        if not isinstance(definition, dict) or len(definition) > 16:
            raise ValueError("artifact query distinct definition is invalid")
        output[str(key)] = {
            str(label): _field_names(fields)
            for label, fields in definition.items()
        }
    return output


def _field_names(value: object) -> list[str]:
    if not isinstance(value, list) or not 1 <= len(value) <= 16:
        raise ValueError("artifact query field aliases must be a bounded array")
    return list(dict.fromkeys(str(item) for item in value if str(item).strip()))


def _matches_filters(
    row: dict[str, object],
    filters: dict[str, dict[str, object]],
    *,
    exclude: str = "",
) -> bool:
    for key, definition in filters.items():
        if key == exclude:
            continue
        candidate = _first_text(row, definition["fields"])
        if candidate and candidate not in definition["values"]:
            return False
    return True


def _first_text(row: dict[str, object], fields: object) -> str:
    for field in fields if isinstance(fields, list) else []:
        value = row.get(field)
        if value is not None and str(value).strip():
            return str(value).strip()
    return ""


def _distinct_rows(
    rows: list[dict[str, object]], fields: dict[str, list[str]],
) -> list[dict[str, str]]:
    output = []
    seen = set()
    for row in rows:
        projected = {
            label: _first_text(row, aliases)
            for label, aliases in fields.items()
        }
        identity = tuple(projected.items())
        if identity in seen or not any(projected.values()):
            continue
        seen.add(identity)
        output.append(projected)
        if len(output) >= 2_000:
            break
    return output


def _sample_indices(
    indices: list[int], values: list[object], maximum: int,
) -> list[int]:
    if len(indices) <= maximum:
        return indices
    if maximum <= 2:
        return [indices[0], indices[-1]][:maximum]
    interior = indices[1:-1]
    bucket_count = max(1, (maximum - 2) // 2)
    selected = {indices[0], indices[-1]}
    for bucket in range(bucket_count):
        start = bucket * len(interior) // bucket_count
        end = (bucket + 1) * len(interior) // bucket_count
        members = interior[start:end]
        if not members:
            continue
        numeric = [
            (float(values[index]), index)
            for index in members
            if index < len(values) and _is_number(values[index])
        ]
        if numeric:
            selected.add(min(numeric)[1])
            selected.add(max(numeric)[1])
        else:
            selected.add(members[0])
            selected.add(members[-1])
    ordered = sorted(selected)
    if len(ordered) <= maximum:
        return ordered
    return [
        ordered[index * (len(ordered) - 1) // (maximum - 1)]
        for index in range(maximum)
    ]


def _range(request: dict[str, object]) -> tuple[float | None, float | None]:
    return _optional_number(request.get("from")), _optional_number(request.get("to"))


def _in_range(value: object, lower: float | None, upper: float | None) -> bool:
    timestamp = _timestamp_number(value)
    if timestamp is None:
        return lower is None and upper is None
    return (lower is None or timestamp >= lower) and (upper is None or timestamp <= upper)


def _timestamp_number(value: object) -> float | None:
    number = _optional_number(value)
    if number is not None:
        if abs(number) > 1_000_000_000 and abs(number) <= 20_000_000_000:
            return number * 1000
        return number
    text = str(value or "").strip()
    if not text:
        return None
    try:
        return datetime.fromisoformat(text.replace("Z", "+00:00")).timestamp() * 1000
    except ValueError:
        return None


def _fields(value: object) -> list[str]:
    if value is None:
        return []
    if not isinstance(value, list) or len(value) > 64:
        raise ValueError("artifact query fields must be an array of at most 64 names")
    return list(dict.fromkeys(str(item) for item in value if str(item).strip()))


def _project_row(
    row: dict[str, object], fields: list[str],
) -> dict[str, object]:
    if not fields:
        return dict(row)
    return {key: row.get(key) for key in fields if key in row}


def _first_numeric(row: dict[str, object], fields: list[str]) -> object:
    for key in fields or list(row):
        if key not in {"timestamp", "series", "strategy", "strategy_id"}:
            value = row.get(key)
            if _is_number(value):
                return value
    return 0


def _mapping_value(value: object, key: str) -> object:
    return value.get(key) if isinstance(value, dict) else None


def _bounded_int(
    value: object, default: int, minimum: int, maximum: int,
) -> int:
    try:
        parsed = int(value) if value is not None else default
    except (TypeError, ValueError) as exc:
        raise ValueError("artifact query integer is invalid") from exc
    return max(minimum, min(maximum, parsed))


def _optional_number(value: object) -> float | None:
    if value is None or value == "":
        return None
    try:
        parsed = float(value)
    except (TypeError, ValueError):
        return None
    return parsed if isfinite(parsed) else None


def _is_number(value: object) -> bool:
    return _optional_number(value) is not None


__all__ = ["JobArtifactQueryService", "query_artifact_value"]

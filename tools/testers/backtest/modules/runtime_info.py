"""Runtime information rows shared by native backtest modules."""

from __future__ import annotations

from typing import Any


def record_runtime_info(
    state: Any,
    *,
    code: str,
    type: str,
    status: str,
    message: str,
    detail: str,
    level: str = "warning",
    details: dict[str, Any] | None = None,
    aggregation_key: str | None = None,
) -> dict[str, Any]:
    """Append or update one strategy-runtime information row.

    `aggregation_key` lets hot event-loop fallbacks update one row instead of
    emitting thousands of duplicates. The UI can still receive the updated row
    through the existing runtime_info SSE channel.
    """

    row = {
        "type": type,
        "status": status,
        "level": level,
        "code": code,
        "message": message,
        "detail": detail,
        "details": dict(details or {}),
    }
    if aggregation_key:
        row["aggregation_key"] = aggregation_key

    runtime_rows = getattr(state, "runtime_info_rows", None)
    if isinstance(runtime_rows, list):
        existing = _find_existing_row(state, runtime_rows, code, aggregation_key)
        if existing is None:
            runtime_rows.append(row)
            _remember_runtime_info_row(state, runtime_rows, row)
        else:
            existing.update(row)
            row = existing

    sink = getattr(state, "runtime_info_sink", None)
    emit = getattr(sink, "emit_runtime_info", None)
    if callable(emit):
        emit(row["message"], level=row["level"], code=row["code"], details=row["details"], row=row)
    return row


def record_runtime_fallback_interval(
    state: Any,
    *,
    code: str,
    type: str,
    status: str,
    product: Any,
    timestamp: Any,
    source: str,
    fallback: str,
    reason: str,
    level: str = "warning",
    extra: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Record a fallback over a time interval, grouped by product/source."""

    product_info = product_display(product)
    ts_text = str(timestamp)
    aggregation_key = _fallback_key(product_info["name"], source, fallback, extra)
    start, end, count, seen_timestamps = _existing_interval(state, code, aggregation_key)
    start = min(start, ts_text) if start else ts_text
    end = max(end, ts_text) if end else ts_text
    if ts_text not in seen_timestamps:
        seen_timestamps.add(ts_text)
        count = count + 1
    details = {
        "product": product_info["name"],
        "product_desc": product_info["desc"],
        "source": source,
        "fallback": fallback,
        "reason": reason,
        "start": start,
        "end": end,
        "count": count,
        "_seen_timestamps": sorted(seen_timestamps),
    }
    if extra:
        details.update(extra)
    display = product_display_text(product_info)
    message = f"{display} 使用 {fallback} 替代 {source}"
    detail = f"{display} 在 {start} 到 {end} 期间因 {reason}，使用 {fallback} 替代 {source}；累计 {count} 次。"
    return record_runtime_info(
        state,
        code=code,
        type=type,
        status=status,
        message=message,
        detail=detail,
        level=level,
        details=details,
        aggregation_key=aggregation_key,
    )


def product_display(product: Any) -> dict[str, str]:
    name = str(getattr(product, "name", product) or "")
    desc = ""
    for attr in ("desc", "description", "display_name", "label"):
        value = getattr(product, attr, None)
        if value:
            desc = str(value)
            break
    return {"name": name, "desc": desc}


def product_display_text(item: dict[str, str]) -> str:
    name = str(item.get("name") or "")
    desc = str(item.get("desc") or "")
    return f"{name}({desc})" if desc and desc != name else name


def _find_existing_row(
    state: Any,
    rows: list[dict[str, Any]],
    code: str,
    aggregation_key: str | None,
) -> dict[str, Any] | None:
    if not aggregation_key:
        return None
    return _runtime_info_row_index(state, rows).get((code, aggregation_key))


def _runtime_info_row_index(state: Any, rows: list[dict[str, Any]]) -> dict[tuple[str, str], dict[str, Any]]:
    cache = getattr(state, "_runtime_info_row_index_cache", None)
    if (
        isinstance(cache, tuple)
        and len(cache) == 3
        and cache[0] == id(rows)
        and cache[1] == len(rows)
        and isinstance(cache[2], dict)
    ):
        return cache[2]
    index: dict[tuple[str, str], dict[str, Any]] = {}
    for row in rows:
        if not isinstance(row, dict):
            continue
        code = row.get("code")
        aggregation_key = row.get("aggregation_key")
        if code and aggregation_key:
            index[(str(code), str(aggregation_key))] = row
    try:
        setattr(state, "_runtime_info_row_index_cache", (id(rows), len(rows), index))
    except Exception:
        pass
    return index


def _remember_runtime_info_row(state: Any, rows: list[dict[str, Any]], row: dict[str, Any]) -> None:
    code = row.get("code")
    aggregation_key = row.get("aggregation_key")
    if not code or not aggregation_key:
        return
    index = _runtime_info_row_index(state, rows)
    index[(str(code), str(aggregation_key))] = row
    try:
        setattr(state, "_runtime_info_row_index_cache", (id(rows), len(rows), index))
    except Exception:
        pass


def _existing_interval(state: Any, code: str, aggregation_key: str) -> tuple[str | None, str | None, int, set[str]]:
    rows = getattr(state, "runtime_info_rows", None)
    if not isinstance(rows, list):
        return None, None, 0, set()
    row = _find_existing_row(state, rows, code, aggregation_key)
    if row is None:
        return None, None, 0, set()
    details = row.get("details") if isinstance(row.get("details"), dict) else {}
    seen_raw = details.get("_seen_timestamps")
    if isinstance(seen_raw, (list, tuple, set)):
        seen = {str(value) for value in seen_raw}
    else:
        seen = set()
        if details.get("start"):
            seen.add(str(details["start"]))
    return (
        str(details.get("start")) if details.get("start") else None,
        str(details.get("end")) if details.get("end") else None,
        int(details.get("count") or 0),
        seen,
    )


def _fallback_key(product_name: str, source: str, fallback: str, extra: dict[str, Any] | None) -> str:
    suffix = ""
    if extra:
        suffix = "|" + "|".join(f"{key}={extra[key]}" for key in sorted(extra))
    return f"{product_name}|{source}->{fallback}{suffix}"

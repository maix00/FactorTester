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
        existing = _find_existing_row(runtime_rows, code, aggregation_key)
        if existing is None:
            runtime_rows.append(row)
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
    start, end, count = _existing_interval(state, code, _fallback_key(product_info["name"], source, fallback, extra))
    ts_text = str(timestamp)
    start = min(start, ts_text) if start else ts_text
    end = max(end, ts_text) if end else ts_text
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
        aggregation_key=_fallback_key(product_info["name"], source, fallback, extra),
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


def _find_existing_row(rows: list[dict[str, Any]], code: str, aggregation_key: str | None) -> dict[str, Any] | None:
    if not aggregation_key:
        return None
    for row in reversed(rows):
        if row.get("code") == code and row.get("aggregation_key") == aggregation_key:
            return row
    return None


def _existing_interval(state: Any, code: str, aggregation_key: str) -> tuple[str | None, str | None, int]:
    rows = getattr(state, "runtime_info_rows", None)
    if not isinstance(rows, list):
        return None, None, 0
    row = _find_existing_row(rows, code, aggregation_key)
    if row is None:
        return None, None, 0
    details = row.get("details") if isinstance(row.get("details"), dict) else {}
    return (
        str(details.get("start")) if details.get("start") else None,
        str(details.get("end")) if details.get("end") else None,
        int(details.get("count") or 0),
    )


def _fallback_key(product_name: str, source: str, fallback: str, extra: dict[str, Any] | None) -> str:
    suffix = ""
    if extra:
        suffix = "|" + "|".join(f"{key}={extra[key]}" for key in sorted(extra))
    return f"{product_name}|{source}->{fallback}{suffix}"

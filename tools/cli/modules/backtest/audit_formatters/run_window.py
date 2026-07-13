"""Run-window audit formatting helpers."""

from __future__ import annotations

from collections.abc import Callable, Mapping, Sequence
from typing import Any


TableRenderer = Callable[[tuple[str, ...], list[tuple[Any, ...]]], list[str]]
Normalize = Callable[[Any], Any]
DisplayKey = Callable[[Any], str]
ScalarCell = Callable[[Any], str]


def run_window_text(
    value: Mapping[str, Any],
    *,
    table_lines: TableRenderer,
    scalar_cell: ScalarCell,
    normalize: Normalize,
) -> str:
    """Render a run-window summary as DataTime rows."""
    rows = value.get("rows")
    if isinstance(rows, list) and rows:
        owner_header = str(value.get("owner_header") or "window")
        table_rows: list[tuple[Any, ...]] = []
        for row in rows:
            if not isinstance(row, Mapping):
                continue
            owner = str(row.get("owner") or "")
            start_dt = datatime_parts(row.get("start_dt"), normalize=normalize)
            end_dt = datatime_parts(row.get("end_dt"), normalize=normalize)
            warmup = scalar_cell(row.get("warmup_window"))
            if start_dt is not None:
                table_rows.append((owner, "start_dt", start_dt["ts"], start_dt["tz"], start_dt["precision"], ""))
            if end_dt is not None:
                table_rows.append((owner, "end_dt", end_dt["ts"], end_dt["tz"], end_dt["precision"], ""))
            if warmup != "null":
                table_rows.append((owner, "warmup_window", "", "", "", warmup))
        if table_rows:
            return "\n".join(table_lines(
                (owner_header, "field", "DataTime.ts", "DataTime.tz", "DataTime.precision", "value"),
                table_rows,
            ))
    start = value.get("start")
    end = value.get("end")
    lines: list[str] = []
    if start not in (None, ""):
        lines.append(f"start_dt = {datatime_text(start, normalize=normalize)}")
    if end not in (None, ""):
        lines.append(f"end_dt   = {datatime_text(end, normalize=normalize)}")
    return "\n".join(lines) if lines else "（无窗口）"


def datatime_text(value: Any, *, normalize: Normalize) -> str:
    parts_dict = datatime_parts(value, normalize=normalize)
    if parts_dict is not None:
        parts = [f"ts={parts_dict['ts']}"]
        if parts_dict["tz"] not in (None, ""):
            parts.append(f"tz={parts_dict['tz']}")
        if parts_dict["precision"] not in (None, ""):
            parts.append(f"precision={parts_dict['precision']}")
        return f"DataTime({', '.join(str(part) for part in parts)})"
    normalized = normalize(value)
    if normalized not in (None, ""):
        return f"DataTime(ts={normalized})"
    return "null"


def datatime_parts(value: Any, *, normalize: Normalize) -> dict[str, str] | None:
    normalized = normalize(value)
    if isinstance(normalized, Mapping):
        ts = normalized.get("ts")
        tz = normalized.get("tz")
        precision = normalized.get("precision")
        if ts not in (None, ""):
            return {
                "ts": str(ts),
                "tz": "" if tz in (None, "") else str(tz),
                "precision": "" if precision in (None, "") else str(precision),
            }
    if normalized not in (None, ""):
        return {"ts": str(normalized), "tz": "", "precision": ""}
    return None


def run_window_summary(
    value: Any,
    *,
    normalize: Normalize,
    display_key: DisplayKey,
) -> dict[str, Any] | None:
    normalized = normalize(value)
    rows: list[dict[str, Any]] = []
    if isinstance(normalized, Mapping) and {"start_dt", "end_dt"} <= set(normalized):
        rows.append({
            "owner": "envelope",
            "start_dt": normalized.get("start_dt"),
            "end_dt": normalized.get("end_dt"),
            "warmup_window": normalized.get("warmup_window"),
        })
    elif isinstance(normalized, Mapping) and normalized and all(isinstance(item, Mapping) for item in normalized.values()):
        grouped: dict[tuple[str, str, str], list[str]] = {}
        payloads: dict[tuple[str, str, str], dict[str, Any]] = {}
        for owner, item in normalized.items():
            if not isinstance(item, Mapping):
                continue
            start_value = item.get("start_dt") or item.get("start")
            end_value = item.get("end_dt") or item.get("end")
            warmup_value = item.get("warmup_window")
            key = (
                display_key(normalize(start_value)),
                display_key(normalize(end_value)),
                display_key(normalize(warmup_value)),
            )
            grouped.setdefault(key, []).append(str(owner))
            payloads.setdefault(key, {
                "start_dt": start_value,
                "end_dt": end_value,
                "warmup_window": warmup_value,
            })
        for key, owners in sorted(grouped.items(), key=lambda item: ", ".join(item[1])):
            payload = payloads[key]
            rows.append({
                "owner": ", ".join(owners),
                "start_dt": payload.get("start_dt"),
                "end_dt": payload.get("end_dt"),
                "warmup_window": payload.get("warmup_window"),
            })
        if rows:
            return {"type": "RunWindowSummary", "owner_header": "strategies", "rows": rows}
    elif isinstance(normalized, Sequence) and not isinstance(normalized, (str, bytes, bytearray)) and len(normalized) >= 2:
        rows.append({"owner": "envelope", "start_dt": normalized[0], "end_dt": normalized[1]})
    if not rows:
        return None
    return {"type": "RunWindowSummary", "owner_header": "window", "rows": rows}


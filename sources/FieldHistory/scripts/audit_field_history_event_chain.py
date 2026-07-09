"""Shared FieldHistory event-chain quality checks.

These checks are independent of the audit horizon.  Both the 2024 replay
coverage audit and the full-history reconstruction audit must reject event
chains that hide missing changes behind synthetic rows or repeat unchanged
non-as-of values.
"""

from __future__ import annotations

import csv
import json
from collections import defaultdict
from collections.abc import Iterable
from pathlib import Path
from typing import Any

import pandas as pd

from tools.data.field_history import _ensure_store_registered
from tools.data.hub import DataHub


def audit_event_chain(*, store_key: str = "openctp", asof_day: str | None = None) -> list[dict[str, str]]:
    """Return event-chain quality issues.

    ``asof_day`` limits the audit to records on/after that day.  The previous
    record immediately before the boundary is still retained as context, so a
    2024+ audit can catch duplicates on the first audited day.
    """

    rows = _load_rows(store_key=store_key)
    grouped: dict[tuple[str, str, str, str, str, str, str, str], list[dict[str, Any]]] = defaultdict(list)
    for row in rows:
        grouped[_chain_key(row)].append(row)

    issues: list[dict[str, str]] = []
    for chain in grouped.values():
        ordered = sorted(chain, key=_sort_key)
        for row in ordered:
            if asof_day and str(row.get("effective_trading_day") or "") < asof_day:
                continue
            if not str(row.get("effective_trading_day") or "").strip() or not str(row.get("effective_timestamp") or "").strip():
                issues.append(_issue_row("missing_effective_datetime", row, {}))
        same_day_rows, same_day_row_ids = _same_day_issue_rows(ordered, asof_day=asof_day)
        for index, row in enumerate(ordered):
            if asof_day and str(row.get("effective_trading_day") or "") < asof_day:
                continue
            previous = _previous_row(ordered, index)
            if previous is None:
                continue
            if _row_id(row) not in same_day_row_ids and _is_non_asof_duplicate(previous, row):
                issues.append(_issue_row("duplicate_non_asof_value", row, previous))
            if _looks_like_synthetic_prior(previous, row):
                issues.append(_issue_row("possible_synthetic_prior_for_previous_value", row, previous))
        issues.extend(_same_day_issues(same_day_rows))
    return issues


def write_event_chain_csv(path: Path, rows: Iterable[dict[str, str]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=_columns())
        writer.writeheader()
        writer.writerows(rows)


def _load_rows(*, store_key: str) -> list[dict[str, Any]]:
    hub = DataHub.get_instance()
    _ensure_store_registered(hub, store_key)
    with hub.connect_store(store_key) as conn:
        agent_rows = conn.execute(
            """
            SELECT data_source, instrument, instrument_label, instrument_type, scope_type, exchange,
                   field_group, field_name, effective_trading_day, effective_timestamp,
                   value_json AS agent_value_json, NULL AS history_value,
                   previous_value_json AS agent_previous_value_json,
                   NULL AS history_previous_value,
                   previous_value_type, contract_codes_json AS agent_contract_codes,
                   NULL AS history_contract_codes,
                   contract_scope_type, contract_code_start, contract_code_end,
                   change_type, source_notice_id, source_url, raw_note,
                   event_id, NULL AS source_key
            FROM agent_field_change_events
            """
        ).fetchall()
        if _table_exists(conn, "historical_field_values"):
            historical_rows = conn.execute(
                """
                SELECT provider AS data_source, instrument, instrument_label, instrument_type, scope_type, exchange,
                       '' AS field_group, field_name, effective_trading_day, effective_timestamp,
                       NULL AS agent_value_json, value AS history_value,
                       NULL AS agent_previous_value_json, previous_value AS history_previous_value,
                       previous_value_type, NULL AS agent_contract_codes,
                       contract_codes AS history_contract_codes,
                       contract_scope_type, contract_code_start, contract_code_end,
                       change_type, source_notice_id, source_url, raw_note,
                       NULL AS event_id, source_key
                FROM historical_field_values
                WHERE source_key NOT LIKE 'agent/%'
                """
            ).fetchall()
        else:
            historical_rows = []
    return [_normalise_row(dict(row)) for row in [*agent_rows, *historical_rows]]


def _normalise_row(row: dict[str, Any]) -> dict[str, Any]:
    row["instrument"] = str(row.get("instrument") or "").upper()
    row["instrument_type"] = str(row.get("instrument_type") or "future")
    row["scope_type"] = str(row.get("scope_type") or "product").lower()
    row["data_source"] = str(row.get("data_source") or "").upper()
    row["exchange"] = str(row.get("exchange") or row.get("data_source") or "").upper()
    row["field_name"] = str(row.get("field_name") or "")
    row["change_type"] = str(row.get("change_type") or "change").lower()
    row["contract_scope_type"] = str(row.get("contract_scope_type") or "all").lower()
    row["contract_code_start"] = str(row.get("contract_code_start") or "").upper()
    row["contract_code_end"] = str(row.get("contract_code_end") or "").upper()
    row["contract_codes"] = _contract_codes(row.get("agent_contract_codes") or row.get("history_contract_codes"))
    row["value"] = _loads_optional(row.get("agent_value_json"), fallback=row.get("history_value"))
    row["previous_value"] = _loads_optional(
        row.get("agent_previous_value_json"),
        fallback=row.get("history_previous_value"),
    )
    return row


def _chain_key(row: dict[str, Any]) -> tuple[str, str, str, str, str, str, str, str]:
    return (
        str(row.get("instrument") or ""),
        str(row.get("instrument_type") or ""),
        str(row.get("exchange") or ""),
        str(row.get("scope_type") or ""),
        str(row.get("field_name") or ""),
        str(row.get("contract_scope_type") or ""),
        json.dumps(row.get("contract_codes") or [], ensure_ascii=False),
        f"{row.get('contract_code_start') or ''}..{row.get('contract_code_end') or ''}",
    )


def _sort_key(row: dict[str, Any]) -> tuple[str, pd.Timestamp, str]:
    day = str(row.get("effective_trading_day") or "")
    ts_text = str(row.get("effective_timestamp") or "")
    ts = pd.Timestamp(ts_text) if ts_text else pd.Timestamp(day or "1900-01-01")
    if ts.tzinfo is not None:
        ts = ts.tz_localize(None)
    source = str(row.get("event_id") or row.get("source_key") or row.get("source_notice_id") or "")
    return day, ts, source


def _previous_row(ordered: list[dict[str, Any]], index: int) -> dict[str, Any] | None:
    if index <= 0:
        return None
    return ordered[index - 1]


def _same_day_issue_rows(
    ordered: list[dict[str, Any]],
    *,
    asof_day: str | None,
) -> tuple[list[dict[str, Any]], set[str]]:
    by_day: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in ordered:
        if str(row.get("change_type") or "") == "asof_confirmed":
            continue
        day = str(row.get("effective_trading_day") or "")
        if asof_day and day < asof_day:
            continue
        by_day[day].append(row)
    rows: list[dict[str, Any]] = []
    participant_ids: set[str] = set()
    for same_day_rows in by_day.values():
        if len(same_day_rows) <= 1:
            continue
        participant_ids.update(_row_id(row) for row in same_day_rows)
        primary = _prefer_clear_notice(same_day_rows)
        for row in same_day_rows:
            if row is primary:
                continue
            row["_same_day_primary"] = primary
            rows.append(row)
    return rows, participant_ids


def _same_day_issues(same_day_rows: list[dict[str, Any]]) -> list[dict[str, str]]:
    issues: list[dict[str, str]] = []
    for row in same_day_rows:
        primary = row["_same_day_primary"]
        status = (
            "same_day_duplicate_value"
            if _same_value(row.get("value"), primary.get("value"))
            else "same_day_conflicting_values"
        )
        issues.append(_issue_row(status, row, primary))
    return issues


def _prefer_clear_notice(rows: list[dict[str, Any]]) -> dict[str, Any]:
    return sorted(
        rows,
        key=lambda row: (
            1 if str(row.get("source_notice_id") or "").strip() else 0,
            1 if str(row.get("source_url") or "").strip() else 0,
            str(row.get("event_id") or row.get("source_key") or ""),
        ),
        reverse=True,
    )[0]


def _is_non_asof_duplicate(previous: dict[str, Any], row: dict[str, Any]) -> bool:
    if str(row.get("change_type") or "") == "asof_confirmed":
        return False
    if str(row.get("change_type") or "") == "exception_unchanged":
        return False
    previous_value = row.get("previous_value")
    if previous_value not in (None, "") and not _same_value(previous_value, previous.get("value")):
        return False
    if not _same_value(row.get("value"), previous.get("value")):
        return False
    if previous_value not in (None, "") and _same_value(previous_value, previous.get("value")):
        return True
    if _same_source(previous, row):
        return True
    return _days_between(previous, row) <= 1


def _looks_like_synthetic_prior(previous: dict[str, Any], row: dict[str, Any]) -> bool:
    previous_value = row.get("previous_value")
    if previous_value is None or previous_value == "":
        return False
    if not _same_value(previous.get("value"), previous_value):
        return False
    if str(previous.get("change_type") or "") == "asof_confirmed":
        return False
    if str(previous.get("change_type") or "") == "exception_unchanged":
        return False
    if str(row.get("effective_trading_day") or "") <= "2010-01-01":
        return False
    if _same_source(previous, row):
        return True
    previous_note = " ".join(str(previous.get(key) or "") for key in ("raw_note", "source_notice_id", "source_url")).lower()
    if any(token in previous_note for token in ("listing", "baseline", "上市", "挂牌")):
        return False
    return any(token in previous_note for token in ("previous_value", "previous value", "prior value", "前值"))


def _same_source(previous: dict[str, Any], row: dict[str, Any]) -> bool:
    previous_notice = str(previous.get("source_notice_id") or "").strip()
    row_notice = str(row.get("source_notice_id") or "").strip()
    if previous_notice and previous_notice == row_notice:
        return True
    previous_url = str(previous.get("source_url") or "").strip()
    row_url = str(row.get("source_url") or "").strip()
    return bool(previous_url and previous_url == row_url)


def _days_between(previous: dict[str, Any], row: dict[str, Any]) -> int:
    try:
        previous_day = pd.Timestamp(previous.get("effective_trading_day")).normalize()
        row_day = pd.Timestamp(row.get("effective_trading_day")).normalize()
    except Exception:
        return 999999
    return abs(int((row_day - previous_day).days))


def _issue_row(status: str, row: dict[str, Any], previous: dict[str, Any]) -> dict[str, str]:
    exchange = str(row.get("exchange") or row.get("data_source") or "")
    notice = str(row.get("source_notice_id") or row.get("event_id") or row.get("source_key") or "")
    previous_notice = str(previous.get("source_notice_id") or previous.get("event_id") or previous.get("source_key") or "")
    return {
        "status": status,
        "exchange": exchange,
        "instrument": str(row.get("instrument") or ""),
        "instrument_label": str(row.get("instrument_label") or ""),
        "field_name": str(row.get("field_name") or ""),
        "detail": (
            f"day={row.get('effective_trading_day') or ''} "
            f"value={row.get('value')!r} change_type={row.get('change_type') or ''} "
            f"notice={notice}; previous_day={previous.get('effective_trading_day') or ''} "
            f"previous_value={previous.get('value')!r} "
            f"previous_change_type={previous.get('change_type') or ''} "
            f"previous_notice={previous_notice}"
        ),
    }


def _loads_optional(value: Any, *, fallback: Any) -> Any:
    if value is None or value == "":
        return fallback
    try:
        return json.loads(str(value))
    except json.JSONDecodeError:
        return value


def _contract_codes(value: Any) -> list[str]:
    if value is None:
        return []
    if isinstance(value, str):
        text = value.strip()
        if not text:
            return []
        try:
            value = json.loads(text)
        except json.JSONDecodeError:
            value = [part.strip() for part in text.split(",") if part.strip()]
    if not isinstance(value, list):
        value = [value]
    return sorted({str(item).strip().upper() for item in value if str(item).strip()})


def _same_value(left: Any, right: Any) -> bool:
    try:
        return abs(float(left) - float(right)) <= 1e-12
    except (TypeError, ValueError):
        return left == right


def _value_key(value: Any) -> str:
    try:
        return f"{float(value):.12g}"
    except (TypeError, ValueError):
        return json.dumps(value, ensure_ascii=False, sort_keys=True)


def _row_id(row: dict[str, Any]) -> str:
    return str(row.get("event_id") or row.get("source_key") or id(row))


def _table_exists(conn: Any, table_name: str) -> bool:
    return bool(conn.execute(
        "SELECT 1 FROM sqlite_master WHERE type IN ('table', 'view') AND name = ?",
        (table_name,),
    ).fetchone())


def _columns() -> list[str]:
    return ["status", "exchange", "instrument", "instrument_label", "field_name", "detail"]

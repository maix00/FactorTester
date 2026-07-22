"""Audit one product's transaction-fee history workflow.

This command is intentionally read-only.  It compares three layers for one
instrument:

1. materialized exchange history in ``historical_field_values``;
2. official settlement-parameter snapshot changes, used as audit hints;
3. curated exchange notices in ``agent_field_change_events``, used as
   source-of-truth events.

It prints gaps that still need listing notices or fee-change notices.  It does
not read or generate event jsonl files.
"""

from __future__ import annotations

import argparse
import csv
import json
import sqlite3
from collections import Counter
from pathlib import Path
from typing import Any

from tools.data.field_history import _ensure_store_registered
from tools.data.field_history_agent_ingest import AGENT_EVENT_TABLE
from tools.data.field_history_agent_ingest import audit_agent_event_previous_values
from tools.data.hub import DataHub
from tools.data.sqlite.db import connect_sqlite

from sources.FieldHistory.scripts.audit_transaction_fee_announcement_alignment import (
    FEE_FIELDS,
    _active_fee_unit_field_before,
    _companion_fee_unit_field,
    _contract_scope_covers,
    _find_notice,
    _is_notice_event,
    _is_snapshot_event,
    _snapshot_key,
    _snapshot_index,
)


DEFAULT_DB = "/Users/maxdeux/Documents/GTHT/data/sqlite/unifieddata.sqlite"
DEFAULT_EVENTS_DIR = "sources/FieldHistory/events/TransactionFee"
RELATED_REQUIRED_FIELDS = {
    "LongMarginRatioByMoney",
    "ShortMarginRatioByMoney",
    "MinLimitOrderVolume",
    "MaxLimitOrderVolume",
    "MaxMarketOrderVolume",
}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("instrument", help="Product code, e.g. CF or CY")
    parser.add_argument("--exchange", default="", help="Exchange code filter, e.g. CZCE")
    parser.add_argument("--db", default=DEFAULT_DB, help="SQLite DB path")
    parser.add_argument(
        "--events-dir",
        default=DEFAULT_EVENTS_DIR,
        help="Deprecated compatibility option; events are read from SQLite.",
    )
    parser.add_argument("--output-csv", default="", help="Optional CSV report path")
    args = parser.parse_args(argv)

    instrument = args.instrument.strip().upper()
    event_source = args.exchange.strip().upper()
    exchange = _normalise_exchange(args.exchange)
    history = _load_history(Path(args.db).expanduser(), instrument=instrument)
    related = _load_related_history(Path(args.db).expanduser(), instrument=instrument, exchange=exchange)
    events = _load_events(Path(args.db).expanduser(), instrument=instrument, data_source=event_source)
    snapshots = [event for event in events if _is_snapshot_event(event)]
    notices = [event for event in events if _is_notice_event(event)]
    snapshot_index = _snapshot_index(snapshots)

    rows = _audit_rows(history, snapshots, notices, snapshot_index=snapshot_index)
    previous_value_rows = _previous_value_audit_rows(args.db, instrument=instrument, data_source=event_source)
    rows.extend(previous_value_rows)
    _print_summary(
        instrument,
        exchange=exchange,
        history=history,
        related=related,
        snapshots=snapshots,
        notices=notices,
        rows=rows,
    )
    if args.output_csv:
        _write_csv(Path(args.output_csv).expanduser(), rows)
    return 0 if not any(row["status"].startswith("missing_") for row in rows) else 2


def _load_history(db: Path, *, instrument: str) -> list[dict[str, Any]]:
    with connect_sqlite(db) as conn:
        return [
            dict(row)
            for row in conn.execute(
                """
                SELECT provider, source_key, instrument, instrument_label, instrument_type,
                       field_name, effective_trading_day, effective_timestamp, value,
                       contract_codes, contract_scope_type, contract_code_start,
                       contract_code_end, change_type, source_url, source_date,
                       source_notice_id, raw_note
                FROM historical_field_values
                WHERE instrument = ?
                  AND field_name IN ({fields})
                ORDER BY effective_trading_day, effective_timestamp, field_name, contract_codes
                """.format(fields=",".join("?" for _ in FEE_FIELDS)),
                (instrument, *sorted(FEE_FIELDS)),
            )
        ]


def _normalise_exchange(value: str) -> str:
    text = value.strip().upper()
    aliases = {
        "CZCE": "CZC",
        "ZCE": "CZC",
        "SHFE": "SHF",
        "DCE": "DCE",
        "CFFEX": "CFE",
        "INE": "INE",
        "GFEX": "GFE",
    }
    return aliases.get(text, text)


def _load_related_history(db: Path, *, instrument: str, exchange: str) -> list[dict[str, Any]]:
    with connect_sqlite(db) as conn:
        return [
            dict(row)
            for row in conn.execute(
                """
                SELECT provider, source_key, instrument, instrument_label, instrument_type,
                       field_name, effective_trading_day, effective_timestamp, value,
                       contract_codes, contract_scope_type, contract_code_start,
                       contract_code_end, change_type, source_url, source_date,
                       source_notice_id, raw_note
                FROM historical_field_values
                WHERE (
                    instrument = ?
                    OR (
                        instrument = '*'
                        AND scope_type = 'exchange_default'
                        AND UPPER(exchange) = ?
                    )
                )
                  AND field_name IN ({fields})
                ORDER BY effective_trading_day, effective_timestamp, field_name, contract_codes
                """.format(fields=",".join("?" for _ in RELATED_REQUIRED_FIELDS)),
                (instrument, exchange, *sorted(RELATED_REQUIRED_FIELDS)),
            )
        ]


def _load_events(db: Path, *, instrument: str, data_source: str) -> list[dict[str, Any]]:
    with connect_sqlite(db) as conn:
        rows = conn.execute(
            """
            SELECT *
            FROM {table}
            WHERE field_group = 'TransactionFee'
              AND instrument = ?
              AND field_name IN ({fields})
              {data_source_filter}
            ORDER BY effective_trading_day, effective_timestamp, field_name, event_id
            """.format(
                table=AGENT_EVENT_TABLE,
                fields=",".join("?" for _ in FEE_FIELDS),
                data_source_filter="AND UPPER(data_source) = ?" if data_source else "",
            ),
            (instrument, *sorted(FEE_FIELDS), *((data_source,) if data_source else ())),
        ).fetchall()
    return [_event_from_agent_row(row) for row in rows]


def _event_from_agent_row(row: sqlite3.Row) -> dict[str, Any]:
    event = dict(row)
    event["value"] = json.loads(event.get("value_json") or "null")
    event["previous_value"] = _loads_json_or_none(event.get("previous_value_json"))
    event["contract_codes"] = json.loads(event.get("contract_codes_json") or "[]")
    event["source_key"] = f"agent/{event.get('data_source')}/{event.get('event_id')}"
    event["source_url"] = event.get("source_url") or ""
    event["source_date"] = event.get("source_accessed_at") or ""
    return event


def _loads_json_or_none(value: Any) -> Any:
    text = str(value or "").strip()
    if not text:
        return None
    return json.loads(text)


def _audit_rows(
    history: list[dict[str, Any]],
    snapshots: list[dict[str, Any]],
    notices: list[dict[str, Any]],
    *,
    snapshot_index: dict[tuple[str, str, str, str, str], dict[str, Any]],
) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for change in [row for row in history if str(row.get("change_type") or "change").lower() == "change"]:
        prior = _prior_baseline(change, history)
        if prior is None:
            rows.append(_history_gap_row("missing_prior_baseline", change, matched=None))
    for snapshot in snapshots:
        exact = _find_notice(snapshot, notices, allow_prior=False)
        if exact is not None:
            rows.append(_snapshot_row("aligned_exact_notice", snapshot, exact))
            continue
        prior = _find_notice(snapshot, notices, allow_prior=True)
        if prior is not None:
            rows.append(_snapshot_row("aligned_prior_notice", snapshot, prior))
            continue
        history_match = _find_history_match(snapshot, history)
        if history_match is not None:
            rows.append(_snapshot_row("aligned_materialized_history", snapshot, history_match))
            continue
        companion = _unit_companion_history_match(snapshot, history, snapshot_index=snapshot_index)
        if companion is not None:
            rows.append(_snapshot_row("aligned_unit_companion", snapshot, companion))
            continue
        rows.append(_snapshot_row("missing_notice_for_snapshot", snapshot, None))
    return sorted(rows, key=lambda row: (row["effective_trading_day"], row["field_name"], row["status"]))


def _previous_value_audit_rows(db: str, *, instrument: str, data_source: str) -> list[dict[str, str]]:
    issues = audit_agent_event_previous_values(store_key=_store_key_for_db(db), data_source=data_source or None)
    rows: list[dict[str, str]] = []
    for issue in issues:
        if str(issue.get("instrument") or "").upper() != instrument:
            continue
        rows.append({
            "status": str(issue.get("status") or ""),
            "instrument": str(issue.get("instrument") or ""),
            "field_name": str(issue.get("field_name") or ""),
            "effective_trading_day": str(issue.get("effective_trading_day") or ""),
            "value": str(issue.get("previous_value") or ""),
            "contract_codes": "",
            "source_notice_id": str(issue.get("source_notice_id") or ""),
            "source_url": "",
            "matched_notice_id": str(issue.get("prior_source_notice_id") or ""),
            "matched_source_url": "",
        })
    return rows


def _store_key_for_db(db: str) -> str:
    db_path = str(Path(db).expanduser())
    if db_path == str(Path(DEFAULT_DB).expanduser()):
        _ensure_store_registered(DataHub.get_instance(), "openctp")
        return "openctp"
    raise ValueError(
        "previous_value audit currently requires a registered DataHub store; "
        f"unsupported db path: {db_path}"
    )


def _prior_baseline(change: dict[str, Any], history: list[dict[str, Any]]) -> dict[str, Any] | None:
    candidates: list[dict[str, Any]] = []
    for row in history:
        if str(row.get("change_type") or "").lower() != "baseline":
            continue
        if str(row.get("field_name") or "") != str(change.get("field_name") or ""):
            continue
        if _time_key(row) >= _time_key(change):
            continue
        if _history_scope_covers(row, change):
            candidates.append(row)
    if not candidates:
        return None
    return sorted(candidates, key=_time_key)[-1]


def _find_history_match(snapshot: dict[str, Any], history: list[dict[str, Any]]) -> dict[str, Any] | None:
    candidates = [
        row
        for row in history
        if str(row.get("field_name") or "") == str(snapshot.get("field_name") or "")
        and _same_float(row.get("value"), snapshot.get("value"))
        and _time_key(row) <= _event_time_key(snapshot)
        and _history_scope_covers(row, snapshot)
    ]
    if not candidates:
        return None
    return sorted(candidates, key=_time_key)[-1]


def _unit_companion_history_match(
    snapshot: dict[str, Any],
    history: list[dict[str, Any]],
    *,
    snapshot_index: dict[tuple[str, str, str, str, str], dict[str, Any]],
) -> dict[str, Any] | None:
    if abs(float(snapshot.get("value") or 0.0)) > 1e-15:
        return None
    field = str(snapshot.get("field_name") or "")
    companion_field = _companion_fee_unit_field(field)
    if not companion_field:
        return None
    companion_snapshot = snapshot_index.get(_snapshot_key(snapshot, companion_field))
    if companion_snapshot is None:
        return None
    if abs(float(companion_snapshot.get("value") or 0.0)) > 1e-15:
        return _find_history_match(companion_snapshot, history)
    companion_match = _find_history_match(companion_snapshot, history)
    if companion_match is not None:
        return companion_match
    active_field = _active_fee_unit_field_before(snapshot, [_event_like_from_history(row) for row in history])
    if active_field != companion_field:
        return None
    return _find_history_match({**companion_snapshot, "field_name": active_field}, history)


def _history_scope_covers(history_row: dict[str, Any], event: dict[str, Any]) -> bool:
    notice = _event_like_from_history(history_row)
    snapshot = _event_like_from_history(event) if "contract_scope_type" in event else event
    return _contract_scope_covers(notice, snapshot)


def _event_like_from_history(row: dict[str, Any]) -> dict[str, Any]:
    event = dict(row)
    codes = event.get("contract_codes")
    if isinstance(codes, str):
        try:
            event["contract_codes"] = json.loads(codes)
        except json.JSONDecodeError:
            event["contract_codes"] = []
    return event


def _history_gap_row(status: str, row: dict[str, Any], *, matched: dict[str, Any] | None) -> dict[str, str]:
    return {
        "status": status,
        "instrument": str(row.get("instrument") or ""),
        "field_name": str(row.get("field_name") or ""),
        "effective_trading_day": str(row.get("effective_trading_day") or ""),
        "value": _display_value(row.get("value")),
        "contract_codes": str(row.get("contract_codes") or "[]"),
        "source_notice_id": str(row.get("source_notice_id") or ""),
        "source_url": str(row.get("source_url") or ""),
        "matched_notice_id": "" if matched is None else str(matched.get("source_notice_id") or ""),
        "matched_source_url": "" if matched is None else str(matched.get("source_url") or ""),
    }


def _snapshot_row(status: str, snapshot: dict[str, Any], matched: dict[str, Any] | None) -> dict[str, str]:
    return {
        "status": status,
        "instrument": str(snapshot.get("instrument") or ""),
        "field_name": str(snapshot.get("field_name") or ""),
        "effective_trading_day": str(snapshot.get("effective_trading_day") or ""),
        "value": _display_value(snapshot.get("value")),
        "contract_codes": json.dumps(snapshot.get("contract_codes") or [], ensure_ascii=False),
        "source_notice_id": str(snapshot.get("source_notice_id") or ""),
        "source_url": str(snapshot.get("source_url") or ""),
        "matched_notice_id": "" if matched is None else str(matched.get("source_notice_id") or ""),
        "matched_source_url": "" if matched is None else str(matched.get("source_url") or ""),
    }


def _time_key(row: dict[str, Any]) -> tuple[str, str]:
    return (str(row.get("effective_trading_day") or ""), str(row.get("effective_timestamp") or ""))


def _event_time_key(event: dict[str, Any]) -> tuple[str, str]:
    return (str(event.get("effective_trading_day") or ""), str(event.get("effective_timestamp") or ""))


def _same_float(left: Any, right: Any) -> bool:
    try:
        left_value = json.loads(left) if isinstance(left, str) else left
    except json.JSONDecodeError:
        left_value = left
    try:
        return abs(float(left_value or 0.0) - float(right or 0.0)) <= 1e-15
    except (TypeError, ValueError):
        return False


def _display_value(value: Any) -> str:
    if value is None:
        return ""
    return str(value)


def _print_summary(
    instrument: str,
    *,
    exchange: str,
    history: list[dict[str, Any]],
    related: list[dict[str, Any]],
    snapshots: list[dict[str, Any]],
    notices: list[dict[str, Any]],
    rows: list[dict[str, str]],
) -> None:
    print(f"TransactionFee product audit: {instrument}" + (f" / {exchange}" if exchange else ""))
    print(f"  materialized_history_rows: {len(history)}")
    print(f"  related_margin_order_rows: {len(related)}")
    present_related = {str(row.get("field_name") or "") for row in related}
    missing_related = sorted(RELATED_REQUIRED_FIELDS - present_related)
    baseline_related = {
        str(row.get("field_name") or "")
        for row in related
        if str(row.get("change_type") or "").lower() == "baseline"
    }
    missing_related_baseline = sorted(RELATED_REQUIRED_FIELDS - baseline_related)
    if missing_related:
        print("  missing_related_fields:")
        for field_name in missing_related:
            print(f"    {field_name}")
    else:
        print("  missing_related_fields: none")
    if missing_related_baseline:
        print("  missing_related_baselines:")
        for field_name in missing_related_baseline:
            print(f"    {field_name}")
    else:
        print("  missing_related_baselines: none")
    print(f"  settlement_snapshot_change_rows: {len(snapshots)}")
    print(f"  notice_event_rows: {len(notices)}")
    print("  status_counts:")
    for status, count in sorted(Counter(row["status"] for row in rows).items()):
        print(f"    {status}: {count}")
    for status in ("missing_prior_baseline", "missing_notice_for_snapshot", "previous_value_mismatch", "missing_prior"):
        selected = [row for row in rows if row["status"] == status]
        if not selected:
            continue
        print(f"  {status} samples:")
        for row in selected[:12]:
            print(
                "    "
                f"{row['effective_trading_day']} {row['field_name']} "
                f"value={row['value']} contracts={row['contract_codes']} "
                f"source={row['source_notice_id']}"
            )


def _write_csv(path: Path, rows: list[dict[str, str]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    columns = [
        "status",
        "instrument",
        "field_name",
        "effective_trading_day",
        "value",
        "contract_codes",
        "source_notice_id",
        "source_url",
        "matched_notice_id",
        "matched_source_url",
    ]
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=columns)
        writer.writeheader()
        writer.writerows(rows)


if __name__ == "__main__":
    raise SystemExit(main())

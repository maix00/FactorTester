"""Correct SHFE listing-notice transaction-fee rows to baselines.

Some SHFE listing notices were originally ingested as ordinary ``change`` rows.
When the source text says the product starts trading on that date, those rows
are listing baselines.  This script fixes the existing event/history rows and
adds inactive volume-unit zero baselines for the same listing scope.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import sqlite3
from typing import Any

from sources.FieldHistory.scripts.ingest_field_history_events import _rebuild_view
from tools.data.field_history import _ensure_store_registered
from tools.data.field_history_agent_ingest import (
    AGENT_EVENT_TABLE,
    append_agent_field_change_events,
    ensure_agent_event_schema,
    materialize_agent_events_to_history,
)
from tools.data.hub import DataHub


FEE_COMPANIONS = {
    "OpenRatioByMoney": "OpenRatioByVolume",
    "CloseRatioByMoney": "CloseRatioByVolume",
    "CloseTodayRatioByMoney": "CloseTodayRatioByVolume",
}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--store-key", default="openctp")
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args(argv)

    hub = DataHub.get_instance()
    _ensure_store_registered(hub, args.store_key)
    with hub.connect_store(args.store_key) as conn:
        ensure_agent_event_schema(conn)
        listing_rows = _listing_money_rows(conn)
        events = build_inactive_unit_events(conn, listing_rows)
        if not args.dry_run:
            _mark_listing_rows_as_baseline(conn, listing_rows)
    if not args.dry_run and events:
        append_agent_field_change_events(events, store_key=args.store_key)
    if not args.dry_run and (listing_rows or events):
        materialize_agent_events_to_history(store_key=args.store_key, field_group="TransactionFee")
        _rebuild_view("TransactionFee", store_key=args.store_key)
    print(json.dumps({
        "listing_rows_corrected": len(listing_rows),
        "inactive_unit_events": len(events),
        "dry_run": bool(args.dry_run),
        "sample_event_ids": [event["event_id"] for event in events[:20]],
    }, ensure_ascii=False, indent=2))
    return 0


def build_inactive_unit_events(conn: sqlite3.Connection, listing_rows: list[sqlite3.Row]) -> list[dict[str, Any]]:
    existing = _existing_keys(conn)
    events: list[dict[str, Any]] = []
    for row in listing_rows:
        event = _inactive_zero_event(row)
        if _event_key(event) in existing:
            continue
        events.append(event)
    return events


def _listing_money_rows(conn: sqlite3.Connection) -> list[sqlite3.Row]:
    return conn.execute(
        f"""
        SELECT *
        FROM {AGENT_EVENT_TABLE}
        WHERE data_source = 'SHFE'
          AND field_group = 'TransactionFee'
          AND field_name IN ({",".join("?" for _ in FEE_COMPANIONS)})
          AND raw_note LIKE '%上市交易%'
          AND source_url LIKE 'https://www.shfe.com.cn/%'
        ORDER BY instrument, effective_trading_day, field_name
        """,
        tuple(FEE_COMPANIONS),
    ).fetchall()


def _mark_listing_rows_as_baseline(conn: sqlite3.Connection, rows: list[sqlite3.Row]) -> None:
    event_ids = [str(row["event_id"]) for row in rows]
    for event_id in event_ids:
        conn.execute(
            f"UPDATE {AGENT_EVENT_TABLE} SET change_type = 'baseline' WHERE event_id = ?",
            (event_id,),
        )
        conn.execute(
            """
            UPDATE historical_field_values
            SET change_type = 'baseline'
            WHERE source_key = ?
            """,
            (f"agent/SHFE/{event_id}",),
        )
    conn.commit()


def _existing_keys(conn: sqlite3.Connection) -> set[tuple[Any, ...]]:
    rows = conn.execute(
        f"""
        SELECT data_source, field_group, instrument, instrument_type, field_name,
               effective_trading_day, COALESCE(effective_timestamp, ''),
               COALESCE(contract_scope_type, 'all'), contract_codes_json,
               COALESCE(contract_code_start, ''), COALESCE(contract_code_end, ''),
               value_json
        FROM {AGENT_EVENT_TABLE}
        WHERE data_source = 'SHFE'
          AND field_group = 'TransactionFee'
        """
    ).fetchall()
    return {tuple(row) for row in rows}


def _inactive_zero_event(row: sqlite3.Row) -> dict[str, Any]:
    source_event_id = str(row["event_id"])
    field_name = FEE_COMPANIONS[str(row["field_name"])]
    event_id = "transaction_fee_" + hashlib.sha1(
        f"shfe-listing-inactive-unit-zero:{source_event_id}:{field_name}".encode("utf-8")
    ).hexdigest()[:24]
    contract_codes = json.loads(row["contract_codes_json"] or "[]")
    return {
        "event_id": event_id,
        "data_source": "SHFE",
        "field_group": "TransactionFee",
        "source_url": row["source_url"],
        "source_accessed_at": row["source_accessed_at"],
        "agent_name": "Agent:SHFE",
        "requester_key_hash": row["requester_key_hash"],
        "instrument": row["instrument"],
        "instrument_label": row["instrument_label"] or "",
        "instrument_type": row["instrument_type"],
        "scope_type": row["scope_type"] or "product",
        "exchange": row["exchange"] or "SHFE",
        "field_name": field_name,
        "effective_trading_day": row["effective_trading_day"],
        "effective_timestamp": row["effective_timestamp"] or "",
        "value": 0,
        "contract_codes": contract_codes,
        "contract_scope_type": row["contract_scope_type"] or "all",
        "contract_code_start": row["contract_code_start"] or "",
        "contract_code_end": row["contract_code_end"] or "",
        "change_type": "baseline",
        "source_notice_id": f"{row['source_notice_id']}-inactive-unit-zero",
        "raw_note": row["raw_note"] or "",
        "evidence_text": row["evidence_text"] or "",
        "parser_notes": (
            "Inactive fee-unit companion baseline generated from the same official "
            f"SHFE listing fee event {source_event_id}. The source quotes fees by "
            "money ratio, so the volume-per-lot unit is inactive at listing."
        ),
    }


def _event_key(event: dict[str, Any]) -> tuple[Any, ...]:
    return (
        event["data_source"],
        event["field_group"],
        event["instrument"],
        event["instrument_type"],
        event["field_name"],
        event["effective_trading_day"],
        event.get("effective_timestamp") or "",
        event.get("contract_scope_type") or "all",
        json.dumps(event.get("contract_codes") or [], ensure_ascii=False),
        event.get("contract_code_start") or "",
        event.get("contract_code_end") or "",
        json.dumps(event["value"], ensure_ascii=False),
    )


if __name__ == "__main__":
    raise SystemExit(main())

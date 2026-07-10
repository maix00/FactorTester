"""Backfill inactive DCE transaction-fee unit zeros from official fee events.

DCE notices may quote transaction fees either by turnover ratio or by fixed
amount per lot.  The exchange source therefore defines one unit as active and
the companion unit as inactive for the same leg/scope.  This script only
mirrors already-ingested official DCE fee events into their inactive companion
zero rows; it does not create new fee values from broker/audit sources.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import sqlite3
from collections.abc import Iterable
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
    "OpenRatioByVolume": "OpenRatioByMoney",
    "CloseRatioByVolume": "CloseRatioByMoney",
    "CloseTodayRatioByVolume": "CloseTodayRatioByMoney",
}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--store-key", default="openctp")
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args(argv)

    events = build_events(store_key=args.store_key)
    if not args.dry_run and events:
        append_agent_field_change_events(events, store_key=args.store_key)
        materialize_agent_events_to_history(store_key=args.store_key, field_group="TransactionFee")
        _rebuild_view("TransactionFee", store_key=args.store_key)
    print(json.dumps({
        "candidate_events": len(events),
        "inserted": 0 if args.dry_run else len(events),
        "sample_event_ids": [event["event_id"] for event in events[:20]],
    }, ensure_ascii=False, indent=2))
    return 0


def build_events(*, store_key: str = "openctp") -> list[dict[str, Any]]:
    hub = DataHub.get_instance()
    _ensure_store_registered(hub, store_key)
    with hub.connect_store(store_key) as conn:
        ensure_agent_event_schema(conn)
        rows = conn.execute(
            f"""
            SELECT *
            FROM {AGENT_EVENT_TABLE}
            WHERE data_source = 'DCE'
              AND field_group = 'TransactionFee'
              AND field_name IN ({",".join("?" for _ in FEE_COMPANIONS)})
              AND (
                  source_url LIKE 'https://www.dce.com.cn/%'
                  OR source_url LIKE 'http://www.dce.com.cn/%'
                  OR source_notice_id LIKE '大商所发〔%'
              )
            ORDER BY instrument, effective_trading_day, effective_timestamp, field_name
            """,
            tuple(FEE_COMPANIONS),
        ).fetchall()
        existing = _existing_keys(conn)

    events: list[dict[str, Any]] = []
    for row in rows:
        if _numeric_event_value(row) == 0.0:
            continue
        event = _inactive_zero_event(row)
        if _event_key(event) in existing:
            continue
        events.append(event)
    return events


def _numeric_event_value(row: sqlite3.Row) -> float:
    try:
        return float(json.loads(row["value_json"]))
    except (TypeError, ValueError, json.JSONDecodeError):
        return 0.0


def _existing_keys(conn: sqlite3.Connection) -> set[tuple[Any, ...]]:
    rows = conn.execute(
        f"""
        SELECT data_source, field_group, instrument, instrument_type, field_name,
               effective_trading_day, COALESCE(effective_timestamp, ''),
               COALESCE(contract_scope_type, 'all'), contract_codes_json,
               COALESCE(contract_code_start, ''), COALESCE(contract_code_end, ''),
               value_json
        FROM {AGENT_EVENT_TABLE}
        WHERE data_source = 'DCE'
          AND field_group = 'TransactionFee'
        """
    ).fetchall()
    return {tuple(row) for row in rows}


def _inactive_zero_event(row: sqlite3.Row) -> dict[str, Any]:
    source_event_id = str(row["event_id"])
    field_name = FEE_COMPANIONS[str(row["field_name"])]
    event_id = "transaction_fee_" + hashlib.sha1(
        f"dce-inactive-unit-zero:{source_event_id}:{field_name}".encode("utf-8")
    ).hexdigest()[:24]
    contract_codes = json.loads(row["contract_codes_json"] or "[]")
    return {
        "event_id": event_id,
        "data_source": "DCE",
        "field_group": "TransactionFee",
        "source_url": row["source_url"],
        "source_accessed_at": row["source_accessed_at"],
        "agent_name": "Agent:DCE",
        "requester_key_hash": row["requester_key_hash"],
        "instrument": row["instrument"],
        "instrument_label": row["instrument_label"] or "",
        "instrument_type": row["instrument_type"],
        "scope_type": row["scope_type"] or "product",
        "exchange": row["exchange"] or "DCE",
        "field_name": field_name,
        "effective_trading_day": row["effective_trading_day"],
        "effective_timestamp": row["effective_timestamp"] or "",
        "value": 0,
        "value_type": "float",
        "contract_codes": contract_codes,
        "contract_scope_type": row["contract_scope_type"] or "all",
        "contract_code_start": row["contract_code_start"] or "",
        "contract_code_end": row["contract_code_end"] or "",
        "change_type": row["change_type"] or "change",
        "source_notice_id": row["source_notice_id"] or "",
        "raw_note": row["raw_note"] or "",
        "evidence_text": row["evidence_text"] or "",
        "parser_notes": (
            "Inactive fee-unit companion row generated from the same official "
            f"DCE fee event {source_event_id}. This records that the companion "
            "fee unit is inactive for this leg and scope."
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

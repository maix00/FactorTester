"""Import agent-cleaned FieldHistory events from JSONL.

The event data lives in ``sources/FieldHistory/events``. This script only owns
validation, duplicate checks, append-only ingestion, materialization, and view
rebuilds. It must not contain source-specific historical event payloads.
"""

from __future__ import annotations

import argparse
import json
import sqlite3
from collections.abc import Iterable, Mapping
from pathlib import Path
from typing import Any

from tools.data.field_history import (
    HISTORICAL_FIELD_TABLE,
    _ensure_store_registered,
    _normalise_contract_scope_type,
)
from tools.data.field_history_agent_ingest import (
    AGENT_EVENT_TABLE,
    append_agent_field_change_events,
    ensure_agent_event_schema,
    materialize_agent_events_to_history,
)
from tools.data.hub import DataHub


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Import FieldHistory agent event JSONL files")
    parser.add_argument("paths", nargs="+", help="JSONL files containing cleaned FieldHistory events")
    parser.add_argument("--store-key", default="openctp", help="DataHub SQLite store key")
    parser.add_argument("--field-group", default="", help="Optional field_group filter")
    parser.add_argument("--requester-key", default="", help="Requester secret; hashed by ingest API and never stored raw")
    parser.add_argument("--requester-key-hash", default="", help="Precomputed requester key hash")
    parser.add_argument("--no-materialize", action="store_true", help="Append events but do not materialize to historical_field_values")
    parser.add_argument("--no-rebuild-view", action="store_true", help="Skip rebuilding known FieldHistory views")
    args = parser.parse_args(argv)

    events = _dedupe_events(_load_events(args.paths, field_group=args.field_group))
    if not events:
        print(json.dumps({"candidate_events": 0, "inserted_events": 0}, ensure_ascii=False, indent=2))
        return 0
    if not args.requester_key and not args.requester_key_hash:
        raise ValueError("provide --requester-key or --requester-key-hash")
    events = [_with_requester(event, requester_key=args.requester_key, requester_key_hash=args.requester_key_hash) for event in events]

    hub = DataHub.get_instance()
    _ensure_store_registered(hub, args.store_key)
    with hub.connect_store(args.store_key) as conn:
        ensure_agent_event_schema(conn)
        missing = [event for event in events if not _event_exists(conn, event)]

    if missing:
        append_agent_field_change_events(missing, store_key=args.store_key)
    materialized = 0
    rebuilt_views: list[str] = []
    if not args.no_materialize:
        for field_group in sorted({str(event["field_group"]) for event in events}):
            materialized += materialize_agent_events_to_history(store_key=args.store_key, field_group=field_group)
            if not args.no_rebuild_view:
                rebuilt_views.extend(_rebuild_view(field_group, store_key=args.store_key))

    print(json.dumps({
        "candidate_events": len(events),
        "inserted_events": len(missing),
        "materialized_records": materialized,
        "rebuilt_views": rebuilt_views,
    }, ensure_ascii=False, indent=2))
    return 0


def _load_events(paths: Iterable[str], *, field_group: str = "") -> list[dict[str, Any]]:
    events: list[dict[str, Any]] = []
    for path_text in paths:
        path = Path(path_text).expanduser().resolve()
        with path.open("r", encoding="utf-8") as handle:
            for line_number, line in enumerate(handle, start=1):
                text = line.strip()
                if not text or text.startswith("#"):
                    continue
                try:
                    event = json.loads(text)
                except json.JSONDecodeError as exc:
                    raise ValueError(f"{path}:{line_number}: invalid JSON") from exc
                if not isinstance(event, Mapping):
                    raise ValueError(f"{path}:{line_number}: event must be a JSON object")
                row = dict(event)
                if field_group and str(row.get("field_group")) != field_group:
                    continue
                _validate_event(row, source=f"{path}:{line_number}")
                events.append(row)
    return events


def _validate_event(event: Mapping[str, Any], *, source: str) -> None:
    required = (
        "event_id",
        "data_source",
        "field_group",
        "source_url",
        "source_accessed_at",
        "agent_name",
        "instrument",
        "instrument_type",
        "field_name",
        "effective_trading_day",
        "value",
    )
    missing = [key for key in required if key not in event or event[key] in (None, "")]
    if missing:
        raise ValueError(f"{source}: missing required keys: {', '.join(missing)}")
    contract_codes = event.get("contract_codes", ())
    if contract_codes is None:
        return
    if not isinstance(contract_codes, list):
        raise ValueError(f"{source}: contract_codes must be a list")
    scope_type = str(event.get("contract_scope_type") or "").strip().lower()
    if scope_type and scope_type not in {"all", "explicit", "from_contract", "range"}:
        raise ValueError(f"{source}: unsupported contract_scope_type={scope_type!r}")
    if scope_type in {"from_contract", "range"} and not str(event.get("contract_code_start") or "").strip():
        raise ValueError(f"{source}: {scope_type} requires contract_code_start")
    if scope_type == "range" and not str(event.get("contract_code_end") or "").strip():
        raise ValueError(f"{source}: range requires contract_code_end")
    change_type = str(event.get("change_type") or "change").strip().lower()
    if change_type not in {"change", "baseline", "reaffirmation", "exception_unchanged"}:
        raise ValueError(f"{source}: unsupported change_type={change_type!r}")


def _dedupe_events(events: list[dict[str, Any]]) -> list[dict[str, Any]]:
    deduped: dict[str, dict[str, Any]] = {}
    for event in events:
        event_id = str(event["event_id"])
        if event_id in deduped and deduped[event_id] != event:
            raise ValueError(f"conflicting FieldHistory event_id={event_id}")
        deduped[event_id] = event
    return list(deduped.values())


def _with_requester(event: dict[str, Any], *, requester_key: str, requester_key_hash: str) -> dict[str, Any]:
    row = dict(event)
    row.pop("requester_key", None)
    if requester_key_hash:
        row["requester_key_hash"] = requester_key_hash
    else:
        row["requester_key"] = requester_key
    return row


def _event_exists(conn: sqlite3.Connection, event: Mapping[str, Any]) -> bool:
    if conn.execute(
        f"SELECT 1 FROM {AGENT_EVENT_TABLE} WHERE event_id = ? LIMIT 1",
        (event["event_id"],),
    ).fetchone():
        return True
    contract_codes_json = json.dumps(event.get("contract_codes") or [], ensure_ascii=False)
    contract_code_start = str(event.get("contract_code_start") or "")
    contract_code_end = str(event.get("contract_code_end") or "")
    contract_scope_type = _normalise_contract_scope_type(
        event.get("contract_scope_type"),
        contract_codes=contract_codes_json,
        start=contract_code_start,
        end=contract_code_end,
    )
    value_json = json.dumps(event["value"], ensure_ascii=False)
    history_columns = {
        row["name"]
        for row in conn.execute(f'PRAGMA table_info("{HISTORICAL_FIELD_TABLE}")').fetchall()
    }
    scope_filters = ""
    scope_params: tuple[str, ...] = ()
    if {"contract_scope_type", "contract_code_start", "contract_code_end"}.issubset(history_columns):
        scope_filters = """
          AND COALESCE(contract_scope_type, '') = COALESCE(?, '')
          AND COALESCE(contract_code_start, '') = COALESCE(?, '')
          AND COALESCE(contract_code_end, '') = COALESCE(?, '')
        """
        scope_params = (contract_scope_type, contract_code_start, contract_code_end)
    existing = conn.execute(
        f"""
        SELECT 1
        FROM {HISTORICAL_FIELD_TABLE}
        WHERE instrument = ?
          AND instrument_type = ?
          AND field_name = ?
          AND effective_trading_day = ?
          AND COALESCE(effective_timestamp, '') = COALESCE(?, '')
          AND contract_codes = ?
          {scope_filters}
          AND value = ?
        LIMIT 1
        """,
        (
            event["instrument"],
            event["instrument_type"],
            event["field_name"],
            event["effective_trading_day"],
            str(event.get("effective_timestamp") or ""),
            contract_codes_json,
            *scope_params,
            value_json,
        ),
    ).fetchone()
    return existing is not None


def _rebuild_view(field_group: str, *, store_key: str) -> list[str]:
    from sources.FieldHistory.views.Unified import save_unified_table as save_all_fields

    rebuilt = ["field_history_unified"]
    save_all_fields(store_key=store_key)
    if field_group == "LimitOrderVolume":
        from sources.FieldHistory.views.LimitOrderVolume import save_unified_table

        save_unified_table(store_key=store_key)
        rebuilt.append("field_history_limit_order_volume_unified")
    if field_group == "TransactionFee":
        from sources.FieldHistory.views.TransactionFee import save_unified_table

        save_unified_table(store_key=store_key)
        rebuilt.extend([
            "field_history_transaction_fee_unified",
            "field_history_transaction_fee_exchange",
            "field_history_transaction_fee_broker_openctp",
        ])
    return rebuilt


if __name__ == "__main__":
    raise SystemExit(main())

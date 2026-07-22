"""Prune redundant inactive fee-unit zero events.

Exchange transaction fees normally use exactly one unit for a leg:
``*RatioByMoney`` or ``*RatioByVolume``.  The inactive companion unit should be
recorded only as an initial baseline, or when a later notice actually switches
the active unit and explicitly deactivates the previous unit.  Repeating the
inactive zero on every fee notice creates fake historical changes.
"""

from __future__ import annotations

import argparse
import json
import sqlite3
from collections import defaultdict
from pathlib import Path
from typing import Any

from tools.data.hub import DataHub
from tools.data.sqlite.db import connect_sqlite


FEE_LEGS = {
    "Open": ("OpenRatioByMoney", "OpenRatioByVolume"),
    "Close": ("CloseRatioByMoney", "CloseRatioByVolume"),
    "CloseToday": ("CloseTodayRatioByMoney", "CloseTodayRatioByVolume"),
}
FEE_FIELDS = {field for pair in FEE_LEGS.values() for field in pair}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--events-dir",
        default="sources/FieldHistory/events/TransactionFee",
        help="Directory containing transaction-fee JSONL event files.",
    )
    parser.add_argument("--rewrite-events", action="store_true", help="Rewrite JSONL files after pruning.")
    parser.add_argument("--store-key", default="", help="Optional DataHub SQLite store key for DB pruning.")
    parser.add_argument("--sqlite-path", default="", help="Optional direct SQLite path for DB pruning.")
    parser.add_argument("--prune-db", action="store_true", help="Delete pruned event rows from DB tables.")
    parser.add_argument(
        "--prune-stale-db",
        action="store_true",
        help="Also delete materialized TransactionFee agent events that no longer exist in the JSONL library.",
    )
    args = parser.parse_args(argv)

    events_dir = Path(args.events_dir).expanduser().resolve()
    file_rows = _load_file_rows(events_dir)
    removable = _find_redundant_zero_event_ids([row for rows in file_rows.values() for row in rows])
    if args.rewrite_events:
        _rewrite_files(file_rows, removable)
    db_deleted: dict[str, int] = {}
    if args.prune_db:
        if args.sqlite_path:
            with connect_sqlite(Path(args.sqlite_path).expanduser()) as conn:
                db_deleted = _delete_from_db(conn, removable)
                if args.prune_stale_db:
                    _add_deleted_counts(db_deleted, _delete_stale_db_events(conn, _current_event_ids(file_rows)))
        elif args.store_key:
            hub = DataHub.get_instance()
            with hub.connect_store(args.store_key) as conn:
                db_deleted = _delete_from_db(conn, removable)
                if args.prune_stale_db:
                    _add_deleted_counts(db_deleted, _delete_stale_db_events(conn, _current_event_ids(file_rows)))
        else:
            raise ValueError("--prune-db requires --sqlite-path or --store-key")
    print(json.dumps({
        "candidate_events": sum(len(rows) for rows in file_rows.values()),
        "redundant_inactive_zero_events": len(removable),
        "rewrite_events": bool(args.rewrite_events),
        "prune_db": bool(args.prune_db),
        "db_deleted": db_deleted,
        "sample_event_ids": sorted(removable)[:30],
    }, ensure_ascii=False, indent=2))
    return 0


def _load_file_rows(events_dir: Path) -> dict[Path, list[dict[str, Any]]]:
    file_rows: dict[Path, list[dict[str, Any]]] = {}
    for path in sorted(events_dir.glob("*.jsonl")):
        rows: list[dict[str, Any]] = []
        with path.open("r", encoding="utf-8") as handle:
            for line_number, line in enumerate(handle, start=1):
                text = line.strip()
                if not text:
                    rows.append({"_raw": line, "_blank": True, "_path": path, "_line_number": line_number})
                    continue
                if text.startswith("#"):
                    rows.append({"_raw": line, "_comment": True, "_path": path, "_line_number": line_number})
                    continue
                row = json.loads(text)
                row["_path"] = path
                row["_line_number"] = line_number
                rows.append(row)
        file_rows[path] = rows
    return file_rows


def _find_redundant_zero_event_ids(rows: list[dict[str, Any]]) -> set[str]:
    grouped: dict[tuple[Any, ...], list[dict[str, Any]]] = defaultdict(list)
    for row in rows:
        if row.get("_blank") or row.get("_comment"):
            continue
        if row.get("field_group") != "TransactionFee":
            continue
        field_name = str(row.get("field_name") or "")
        if field_name not in FEE_FIELDS:
            continue
        if "settlement-parameters-" in str(row.get("source_notice_id") or ""):
            continue
        grouped[_group_key(row)].append(row)

    removable: set[str] = set()
    for group_rows in grouped.values():
        state: dict[str, float | None] = {field: None for field in FEE_FIELDS}
        for _, batch in _iter_batches(group_rows):
            batch_by_field = {str(row.get("field_name") or ""): row for row in batch}
            keep_zero: set[str] = set()
            for row in batch:
                field = str(row.get("field_name") or "")
                value = _float_value(row.get("value"))
                if value is None:
                    continue
                if value != 0.0:
                    continue
                if str(row.get("change_type") or "").lower() == "baseline" and state.get(field) is None:
                    keep_zero.add(_event_id(row))
                    continue
                if (state.get(field) or 0.0) != 0.0:
                    keep_zero.add(_event_id(row))
                    continue
                other = _other_unit_field(field)
                other_row = batch_by_field.get(other)
                if other_row is not None and (_float_value(other_row.get("value")) or 0.0) != 0.0:
                    if (state.get(field) or 0.0) != 0.0:
                        keep_zero.add(_event_id(row))
            for row in batch:
                field = str(row.get("field_name") or "")
                value = _float_value(row.get("value"))
                if value is None:
                    continue
                event_id = _event_id(row)
                if value == 0.0 and event_id not in keep_zero:
                    removable.add(event_id)
                    continue
                state[field] = value
    return removable


def _group_key(row: dict[str, Any]) -> tuple[Any, ...]:
    field = str(row.get("field_name") or "")
    leg = _leg_for_field(field)
    return (
        row.get("data_source"),
        row.get("instrument"),
        row.get("instrument_type"),
        leg,
        row.get("contract_scope_type") or "",
        tuple(row.get("contract_codes") or []),
        row.get("contract_code_start") or "",
        row.get("contract_code_end") or "",
    )


def _iter_batches(rows: list[dict[str, Any]]) -> list[tuple[tuple[str, str, str], list[dict[str, Any]]]]:
    batches: dict[tuple[str, str, str], list[dict[str, Any]]] = defaultdict(list)
    for row in rows:
        key = (
            str(row.get("effective_trading_day") or ""),
            str(row.get("effective_timestamp") or ""),
            str(row.get("source_notice_id") or ""),
        )
        batches[key].append(row)
    return sorted(batches.items(), key=lambda item: item[0])


def _rewrite_files(file_rows: dict[Path, list[dict[str, Any]]], removable: set[str]) -> None:
    for path, rows in file_rows.items():
        changed = False
        output: list[str] = []
        for row in rows:
            if row.get("_blank") or row.get("_comment"):
                output.append(str(row.get("_raw") or ""))
                continue
            if _event_id(row) in removable:
                changed = True
                continue
            clean = {k: v for k, v in row.items() if not k.startswith("_")}
            output.append(json.dumps(clean, ensure_ascii=False, sort_keys=True) + "\n")
        if changed:
            path.write_text("".join(output), encoding="utf-8")


def _delete_from_db(conn: sqlite3.Connection, removable: set[str]) -> dict[str, int]:
    if not removable:
        return {"agent_field_change_events": 0, "historical_field_values": 0}
    source_keys = [f"agent/%/{event_id}" for event_id in removable]
    agent_deleted = 0
    history_deleted = 0
    for event_id in sorted(removable):
        agent_deleted += conn.execute(
            "DELETE FROM agent_field_change_events WHERE event_id = ?",
            (event_id,),
        ).rowcount
        history_deleted += conn.execute(
            "DELETE FROM historical_field_values WHERE source_key LIKE ?",
            (f"agent/%/{event_id}",),
        ).rowcount
    conn.commit()
    return {"agent_field_change_events": agent_deleted, "historical_field_values": history_deleted}


def _delete_stale_db_events(conn: sqlite3.Connection, current_event_ids: set[str]) -> dict[str, int]:
    rows = conn.execute(
        """
        SELECT event_id
        FROM agent_field_change_events
        WHERE field_group = 'TransactionFee'
        """
    ).fetchall()
    stale = sorted(str(row[0]) for row in rows if str(row[0]) not in current_event_ids)
    if not stale:
        return {"stale_agent_field_change_events": 0, "stale_historical_field_values": 0}
    agent_deleted = 0
    history_deleted = 0
    for event_id in stale:
        agent_deleted += conn.execute(
            "DELETE FROM agent_field_change_events WHERE event_id = ?",
            (event_id,),
        ).rowcount
        history_deleted += conn.execute(
            "DELETE FROM historical_field_values WHERE source_key LIKE ?",
            (f"agent/%/{event_id}",),
        ).rowcount
    conn.commit()
    return {"stale_agent_field_change_events": agent_deleted, "stale_historical_field_values": history_deleted}


def _current_event_ids(file_rows: dict[Path, list[dict[str, Any]]]) -> set[str]:
    return {
        _event_id(row)
        for rows in file_rows.values()
        for row in rows
        if not row.get("_blank") and not row.get("_comment") and row.get("field_group") == "TransactionFee"
    }


def _add_deleted_counts(target: dict[str, int], extra: dict[str, int]) -> None:
    for key, value in extra.items():
        target[key] = target.get(key, 0) + value


def _leg_for_field(field_name: str) -> str:
    for leg, fields in FEE_LEGS.items():
        if field_name in fields:
            return leg
    raise ValueError(f"unsupported fee field: {field_name}")


def _other_unit_field(field_name: str) -> str:
    for money_field, volume_field in FEE_LEGS.values():
        if field_name == money_field:
            return volume_field
        if field_name == volume_field:
            return money_field
    raise ValueError(f"unsupported fee field: {field_name}")


def _float_value(value: Any) -> float | None:
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _event_id(row: dict[str, Any]) -> str:
    return str(row.get("event_id") or "")


if __name__ == "__main__":
    raise SystemExit(main())

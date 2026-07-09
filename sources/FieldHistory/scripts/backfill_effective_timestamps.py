"""Backfill missing FieldHistory effective timestamps from audited session rules."""

from __future__ import annotations

import argparse
from datetime import datetime
from typing import Any

import pandas as pd

from sources.LocalCNFutures import SOURCE_DATA_DIR
from tools.data.field_history import HISTORICAL_FIELD_TABLE, _ensure_store_registered
from tools.data.field_history_agent_ingest import AGENT_EVENT_TABLE, ensure_agent_event_schema
from tools.data.hub import DataHub


DAY_OPEN = "09:00:00"
NIGHT_OPEN = "21:00:00"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--store-key", default="openctp")
    parser.add_argument("--data-source", required=True, help="Agent data_source, e.g. CZCE")
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args(argv)

    _ensure_store_registered(DataHub.get_instance(), args.store_key)
    trading_days = _load_local_cnfutures_trading_days()
    updates = _planned_updates(args.store_key, data_source=args.data_source, trading_days=trading_days)
    sync_updates = _planned_materialized_sync(args.store_key, data_source=args.data_source)
    print("FieldHistory timestamp backfill")
    print(f"  data_source: {args.data_source}")
    print(f"  planned_updates: {len(updates)}")
    print(f"  planned_materialized_sync: {len(sync_updates)}")
    for row in updates[:80]:
        print(
            "  "
            f"{row['event_id']} {row['instrument']} {row['field_name']} "
            f"{row['effective_trading_day']} -> {row['effective_timestamp']}"
        )
    if args.dry_run or (not updates and not sync_updates):
        return 0
    _apply_updates(args.store_key, updates, sync_updates)
    return 0


def _planned_updates(
    store_key: str,
    *,
    data_source: str,
    trading_days: pd.DatetimeIndex,
) -> list[dict[str, str]]:
    hub = DataHub.get_instance()
    with hub.connect_store(store_key) as conn:
        ensure_agent_event_schema(conn)
        rows = conn.execute(
            f"""
            SELECT event_id, data_source, field_group, instrument, field_name, effective_trading_day,
                   source_notice_id, raw_note, evidence_text, parser_notes
            FROM {AGENT_EVENT_TABLE}
            WHERE data_source = ?
              AND COALESCE(effective_timestamp, '') = ''
            ORDER BY source_notice_id, instrument, field_name, event_id
            """,
            (data_source,),
        ).fetchall()
    updates: list[dict[str, str]] = []
    for row in rows:
        record = dict(row)
        session = _infer_session(record)
        if session is None:
            continue
        updates.append({
            "event_id": str(record["event_id"]),
            "data_source": str(record["data_source"]),
            "instrument": str(record["instrument"]),
            "field_name": str(record["field_name"]),
            "effective_trading_day": str(record["effective_trading_day"]),
            "effective_timestamp": _timestamp_for_session(
                str(record["effective_trading_day"]),
                session,
                trading_days=trading_days,
                data_source=str(record["data_source"]),
            ),
        })
    return updates


def _planned_materialized_sync(store_key: str, *, data_source: str) -> list[dict[str, str]]:
    hub = DataHub.get_instance()
    with hub.connect_store(store_key) as conn:
        ensure_agent_event_schema(conn)
        rows = conn.execute(
            f"""
            SELECT a.event_id, a.data_source, a.effective_timestamp
            FROM {AGENT_EVENT_TABLE} a
            JOIN {HISTORICAL_FIELD_TABLE} h
              ON h.source_key = 'agent/' || a.data_source || '/' || a.event_id
            WHERE a.data_source = ?
              AND COALESCE(a.effective_timestamp, '') != ''
              AND COALESCE(h.effective_timestamp, '') = ''
            ORDER BY a.source_notice_id, a.instrument, a.field_name, a.event_id
            """,
            (data_source,),
        ).fetchall()
    return [
        {
            "event_id": str(row["event_id"]),
            "data_source": str(row["data_source"]),
            "effective_timestamp": str(row["effective_timestamp"]),
        }
        for row in rows
    ]


def _infer_session(record: dict[str, Any]) -> str | None:
    text = " ".join(
        str(record.get(key) or "")
        for key in ("raw_note", "evidence_text", "parser_notes")
    )
    # Mixed CZCE notices need product-level interpretation.
    notice = str(record.get("source_notice_id") or "")
    instrument = str(record.get("instrument") or "").upper()
    if notice == "郑商函〔2026〕91号":
        if instrument in {"SR", "RM"}:
            return "night"
        if instrument in {"PK", "SF", "SM"}:
            return "day"
    if "当晚夜盘" in text or "夜盘交易时起" in text or "夜盘交易小节时起" in text:
        return "night"
    if "夜盘" in text and "日起" not in text and "交易起" not in text:
        return "night"
    if notice.endswith("-inactive-unit-zero"):
        return "day"
    if "自" in text and ("日起" in text or "交易起" in text or "上市" in text):
        return "day"
    if str(record.get("field_group") or "") in {"TransactionFee", "LimitOrderVolume", "TradingRules"}:
        notice = str(record.get("source_notice_id") or "")
        if notice.startswith(("郑商函", "郑商发", "郑商所发", "郑商所公告")):
            return "day"
        if notice:
            return "day"
    if str(record.get("field_name") or "").endswith("OrderVolume"):
        return "day"
    return None


def _timestamp_for_session(
    trading_day: str,
    session: str,
    *,
    trading_days: pd.DatetimeIndex,
    data_source: str,
) -> str:
    day = datetime.fromisoformat(trading_day[:10]).date()
    if session == "night":
        previous = _previous_trading_day(day, trading_days=trading_days)
        return f"{previous.strftime('%Y-%m-%d')} {NIGHT_OPEN}"
    return f"{day.isoformat()} {_day_open_for_source(data_source)}"


def _apply_updates(
    store_key: str,
    updates: list[dict[str, str]],
    sync_updates: list[dict[str, str]],
) -> None:
    hub = DataHub.get_instance()
    with hub.connect_store(store_key) as conn:
        ensure_agent_event_schema(conn)
        if updates:
            conn.executemany(
                f"""
                UPDATE {AGENT_EVENT_TABLE}
                SET effective_timestamp = ?
                WHERE event_id = ?
                  AND COALESCE(effective_timestamp, '') = ''
                """,
                [(row["effective_timestamp"], row["event_id"]) for row in updates],
            )
        combined = [*updates, *sync_updates]
        if combined:
            conn.executemany(
                f"""
                UPDATE {HISTORICAL_FIELD_TABLE}
                SET effective_timestamp = ?
                WHERE source_key = ?
                  AND COALESCE(effective_timestamp, '') = ''
                """,
                [
                    (row["effective_timestamp"], f"agent/{row['data_source']}/{row['event_id']}")
                    for row in combined
                ],
            )


def _load_local_cnfutures_trading_days() -> pd.DatetimeIndex:
    path = f"{SOURCE_DATA_DIR}/data_dayk.parquet"
    frame = pd.read_parquet(path, columns=["trading_day"])
    days = pd.DatetimeIndex(pd.to_datetime(frame["trading_day"], errors="coerce").dropna().unique())
    days = days.normalize().sort_values().tz_localize(None)
    if days.empty:
        raise RuntimeError(f"no trading days found in {path}")
    return days


def _previous_trading_day(day: Any, *, trading_days: pd.DatetimeIndex) -> pd.Timestamp:
    normalized = pd.Timestamp(day).normalize().tz_localize(None)
    position = trading_days.searchsorted(normalized, side="left") - 1
    if position < 0:
        raise RuntimeError(f"cannot resolve previous trading day before {normalized.date()}")
    return pd.Timestamp(trading_days[position])


def _day_open_for_source(data_source: str) -> str:
    return "09:30:00" if str(data_source).upper() in {"CFFEX", "CFE"} else DAY_OPEN


if __name__ == "__main__":
    raise SystemExit(main())

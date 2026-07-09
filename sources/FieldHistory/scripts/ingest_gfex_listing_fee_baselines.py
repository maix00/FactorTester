"""Ingest GFEX listing-notice transaction-fee baselines.

These events come from GFEX official listing notices, not broker schedules.
They are true listing baselines for products listed after the 2024 audit
boundary, so they use ``change_type=baseline`` instead of ``asof_confirmed``.
"""

from __future__ import annotations

import argparse
import hashlib
import json
from typing import Any

from sources.FieldHistory.scripts.ingest_field_history_events import _rebuild_view
from tools.data.field_history import _ensure_store_registered
from tools.data.field_history_agent_ingest import (
    append_agent_field_change_events,
    ensure_agent_event_schema,
    materialize_agent_events_to_history,
)
from tools.data.hub import DataHub


LISTING_NOTICES = {
    "PS": {
        "label": "多晶硅",
        "source_url": "http://www.gfex.com.cn/gfex/tzts/202412/34bc2f9dbfc34b4b81e1a043ff526589.shtml",
        "source_notice_id": "广期所发〔2024〕354号",
        "effective_trading_day": "2024-12-26",
        "effective_timestamp": "2024-12-26 09:00:00",
        "raw_note": "多晶硅期货合约自2024年12月26日起上市交易；交易手续费为成交金额的万分之一。",
        "close_today_money": 0.0001,
    },
    "PT": {
        "label": "铂",
        "source_url": "http://www.gfex.com.cn/gfex/tzts/202508/4d8af56888c84490b525d5d8fdd729f6.shtml",
        "source_notice_id": "GFEX-2025-08-21-PT-listing",
        "effective_trading_day": "2025-11-27",
        "effective_timestamp": "2025-11-27 09:00:00",
        "raw_note": "铂期货合约自2025年11月27日起上市交易；交易手续费为成交金额的万分之一，免收日内平今仓交易手续费。",
        "close_today_money": 0.0,
    },
    "PD": {
        "label": "钯",
        "source_url": "http://www.gfex.com.cn/gfex/tzts/202508/5ff7c8717a4a44708e650a08b198254f.shtml",
        "source_notice_id": "GFEX-2025-08-21-PD-listing",
        "effective_trading_day": "2025-11-27",
        "effective_timestamp": "2025-11-27 09:00:00",
        "raw_note": "钯期货合约自2025年11月27日起上市交易；交易手续费为成交金额的万分之一，免收日内平今仓交易手续费。",
        "close_today_money": 0.0,
    },
}

LISTING_BASELINE_NOTICE_IDS = {notice["source_notice_id"] for notice in LISTING_NOTICES.values()}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--store-key", default="openctp")
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args(argv)

    events = build_events(store_key=args.store_key)
    listing_rows: list[str] = []
    if not args.dry_run:
        with DataHub.get_instance().connect_store(args.store_key) as conn:
            listing_rows = _listing_rows_to_mark_baseline(conn)
            _mark_listing_rows_as_baseline(conn, listing_rows)
    if not args.dry_run and events:
        append_agent_field_change_events(events, store_key=args.store_key)
        materialize_agent_events_to_history(store_key=args.store_key, field_group="TransactionFee")
        _rebuild_view("TransactionFee", store_key=args.store_key)
    print(json.dumps({
        "candidate_events": len(events),
        "inserted": 0 if args.dry_run else len(events),
        "listing_rows_corrected": 0 if args.dry_run else len(listing_rows),
        "sample_event_ids": [event["event_id"] for event in events[:20]],
    }, ensure_ascii=False, indent=2))
    return 0


def build_events(*, store_key: str = "openctp") -> list[dict[str, Any]]:
    hub = DataHub.get_instance()
    _ensure_store_registered(hub, store_key)
    with hub.connect_store(store_key) as conn:
        ensure_agent_event_schema(conn)
        existing = {
            tuple(row)
            for row in conn.execute(
                """
                SELECT data_source, field_group, instrument, instrument_type, field_name,
                       effective_trading_day, COALESCE(effective_timestamp, ''),
                       COALESCE(contract_scope_type, 'all'), contract_codes_json,
                       COALESCE(contract_code_start, ''), COALESCE(contract_code_end, ''),
                       value_json
                FROM agent_field_change_events
                WHERE data_source = 'GFEX'
                  AND field_group = 'TransactionFee'
                """
            ).fetchall()
        }
    events = [_event(instrument, field, value, notice) for instrument, notice in LISTING_NOTICES.items() for field, value in _fee_fields(notice).items()]
    return [event for event in events if _event_key(event) not in existing]


def _fee_fields(notice: dict[str, Any]) -> dict[str, float]:
    close_today_money = float(notice["close_today_money"])
    return {
        "OpenRatioByMoney": 0.0001,
        "OpenRatioByVolume": 0.0,
        "CloseRatioByMoney": 0.0001,
        "CloseRatioByVolume": 0.0,
        "CloseTodayRatioByMoney": close_today_money,
        "CloseTodayRatioByVolume": 0.0,
    }


def _event(instrument: str, field_name: str, value: float, notice: dict[str, Any]) -> dict[str, Any]:
    event_id = "transaction_fee_" + hashlib.sha1(
        f"gfex-listing:{instrument}:{field_name}:{notice['effective_trading_day']}:{value}".encode("utf-8")
    ).hexdigest()[:24]
    return {
        "event_id": event_id,
        "data_source": "GFEX",
        "field_group": "TransactionFee",
        "source_url": notice["source_url"],
        "source_accessed_at": "2026-07-09T00:00:00+08:00",
        "agent_name": "Agent:GFEX",
        "requester_key": "field-history-official-gfex-listing",
        "instrument": instrument,
        "instrument_label": notice["label"],
        "instrument_type": "future",
        "scope_type": "product",
        "exchange": "GFEX",
        "field_name": field_name,
        "effective_trading_day": notice["effective_trading_day"],
        "effective_timestamp": notice["effective_timestamp"],
        "value": value,
        "contract_codes": [],
        "contract_scope_type": "all",
        "change_type": "baseline",
        "source_notice_id": notice["source_notice_id"],
        "raw_note": notice["raw_note"],
        "evidence_text": notice["raw_note"],
        "parser_notes": (
            "Official GFEX listing-notice baseline. TTRADE/hedge fee text, when present, "
            "is not mapped to normal close-today fee fields."
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


def _listing_rows_to_mark_baseline(conn: Any) -> list[str]:
    placeholders = ",".join("?" for _ in LISTING_BASELINE_NOTICE_IDS)
    rows = conn.execute(
        f"""
        SELECT event_id
        FROM agent_field_change_events
        WHERE data_source = 'GFEX'
          AND field_group = 'TransactionFee'
          AND source_notice_id IN ({placeholders})
          AND change_type <> 'baseline'
          AND contract_scope_type = 'all'
        """,
        tuple(LISTING_BASELINE_NOTICE_IDS),
    ).fetchall()
    return [str(row["event_id"]) for row in rows]


def _mark_listing_rows_as_baseline(conn: Any, event_ids: list[str]) -> None:
    if not event_ids:
        return
    placeholders = ",".join("?" for _ in event_ids)
    conn.execute(
        f"UPDATE agent_field_change_events SET change_type = 'baseline' WHERE event_id IN ({placeholders})",
        tuple(event_ids),
    )
    source_keys = [f"agent/GFEX/{event_id}" for event_id in event_ids]
    placeholders = ",".join("?" for _ in source_keys)
    conn.execute(
        f"UPDATE historical_field_values SET change_type = 'baseline' WHERE source_key IN ({placeholders})",
        tuple(source_keys),
    )
    conn.commit()


if __name__ == "__main__":
    raise SystemExit(main())

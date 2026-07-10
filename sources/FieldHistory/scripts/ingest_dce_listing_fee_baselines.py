"""Ingest DCE listing-notice historical-field baselines.

These events come from DCE official listing notices, not broker schedules.
They are true listing baselines for products listed after the 2024 audit
boundary, so they use ``change_type=baseline`` instead of ``asof_confirmed``.

Numeric product/contract rules stated by the listing notice are stored.
Statements such as "same as the corresponding contract" are materialized as
product-level listing baselines only by resolving the corresponding product's
current FieldHistory value at the listing effective trading day.  They are not
exchange-default rows.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import sqlite3
from typing import Any

from sources.FieldHistory.scripts.ingest_field_history_events import _rebuild_view
from tools.data.field_history import (
    HistoricalFieldFallbackPolicy,
    _ensure_store_registered,
    load_historical_field_provider,
)
from tools.data.field_history_agent_ingest import (
    AGENT_EVENT_TABLE,
    append_agent_field_change_events,
    ensure_agent_event_schema,
    materialize_agent_events_to_history,
)
from tools.data.hub import DataHub


LISTING_NOTICES = {
    "BZ": {
        "label": "纯苯",
        "source_url": "https://www.dce.com.cn/dce/content/2025/ywggytz/8637864.html",
        "source_notice_id": "大商所发〔2025〕243号",
        "effective_trading_day": "2025-07-08",
        "effective_timestamp": "2025-07-08 09:00:00",
        "raw_note": "纯苯期货合约上市交易；交易手续费收取标准为成交金额的万分之1，套期保值交易手续费收取标准为成交金额的万分之0.5。",
        "fee_unit": "money",
        "fee_value": 0.0001,
        "margin": 0.08,
        "limit": 0.07,
        "volume_multiple": 30.0,
        "price_tick": 1.0,
        "rule_note": "合约涨跌停板幅度为上一交易日结算价的7%，合约交易保证金水平为合约价值的8%。",
    },
    "LG": {
        "label": "原木",
        "source_url": "https://www.dce.com.cn/dce/content/2024/ywggytz/8620259.html",
        "source_notice_id": "DCE-2024-LG-listing",
        "effective_trading_day": "2024-11-18",
        "effective_timestamp": "2024-11-18 09:00:00",
        "raw_note": "原木期货上市交易；原木期货交易手续费收取标准为成交金额的万分之一，套期保值交易手续费收取标准为成交金额的万分之0.5。",
        "fee_unit": "money",
        "fee_value": 0.0001,
        "margin": 0.08,
        "limit": 0.06,
        "volume_multiple": 90.0,
        "price_tick": 0.5,
        "rule_note": "合约涨跌停板幅度为上一交易日结算价的6%，合约交易保证金水平为合约价值的8%。",
    },
    "L_F": {
        "label": "聚乙烯月均价期货",
        "source_url": "https://www.dce.com.cn/dce/content/2025/ywggytz/18623631.html",
        "source_notice_id": "DCE-2025-chemical-month-average-listing",
        "effective_trading_day": "2025-10-29",
        "effective_timestamp": "2025-10-28 21:00:00",
        "raw_note": "三个化工品月均价期货上市交易；交易手续费收取标准为1元/手，套期保值交易手续费收取标准为0.5元/手。",
        "fee_unit": "volume",
        "fee_value": 1.0,
        "inherits_from": "L",
        "volume_multiple": 5.0,
        "price_tick": 1.0,
        "rule_note": "交易保证金比例、涨跌停板幅度与对应合约保持一致；交易单位5吨/手，最小变动价位1元/吨。",
    },
    "PP_F": {
        "label": "聚丙烯月均价期货",
        "source_url": "https://www.dce.com.cn/dce/content/2025/ywggytz/18623631.html",
        "source_notice_id": "DCE-2025-chemical-month-average-listing",
        "effective_trading_day": "2025-10-29",
        "effective_timestamp": "2025-10-28 21:00:00",
        "raw_note": "三个化工品月均价期货上市交易；交易手续费收取标准为1元/手，套期保值交易手续费收取标准为0.5元/手。",
        "fee_unit": "volume",
        "fee_value": 1.0,
        "inherits_from": "PP",
        "volume_multiple": 5.0,
        "price_tick": 1.0,
        "rule_note": "交易保证金比例、涨跌停板幅度与对应合约保持一致；交易单位5吨/手，最小变动价位1元/吨。",
    },
    "V_F": {
        "label": "聚氯乙烯月均价期货",
        "source_url": "https://www.dce.com.cn/dce/content/2025/ywggytz/18623631.html",
        "source_notice_id": "DCE-2025-chemical-month-average-listing",
        "effective_trading_day": "2025-10-29",
        "effective_timestamp": "2025-10-28 21:00:00",
        "raw_note": "三个化工品月均价期货上市交易；交易手续费收取标准为1元/手，套期保值交易手续费收取标准为0.5元/手。",
        "fee_unit": "volume",
        "fee_value": 1.0,
        "inherits_from": "V",
        "volume_multiple": 5.0,
        "price_tick": 1.0,
        "rule_note": "交易保证金比例、涨跌停板幅度与对应合约保持一致；交易单位5吨/手，最小变动价位1元/吨。",
    },
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
        listing_rows = _listing_rows_to_fix(conn)
    events = build_events(store_key=args.store_key)
    listing_event_ids = [row["event_id"] for row in listing_rows]
    if not args.dry_run and listing_event_ids:
        with hub.connect_store(args.store_key) as conn:
            _mark_listing_rows_as_baseline(conn, listing_event_ids)
    if not args.dry_run and events:
        append_agent_field_change_events(events, store_key=args.store_key)
    if not args.dry_run and (events or listing_rows):
        for field_group in {"TransactionFee", "Margin", "TradingRules"}:
            materialize_agent_events_to_history(store_key=args.store_key, field_group=field_group)
            _rebuild_view(field_group, store_key=args.store_key)
    print(json.dumps({
        "candidate_events": len(events),
        "listing_rows_corrected": len(listing_rows),
        "inserted": 0 if args.dry_run else len(events),
        "sample_event_ids": [event["event_id"] for event in events[:20]],
    }, ensure_ascii=False, indent=2))
    return 0


def _fee_fields(notice: dict[str, Any]) -> dict[str, float]:
    value = float(notice["fee_value"])
    if notice["fee_unit"] == "money":
        return {
            "OpenRatioByMoney": value,
            "OpenRatioByVolume": 0.0,
            "CloseRatioByMoney": value,
            "CloseRatioByVolume": 0.0,
            "CloseTodayRatioByMoney": value,
            "CloseTodayRatioByVolume": 0.0,
        }
    if notice["fee_unit"] == "volume":
        return {
            "OpenRatioByMoney": 0.0,
            "OpenRatioByVolume": value,
            "CloseRatioByMoney": 0.0,
            "CloseRatioByVolume": value,
            "CloseTodayRatioByMoney": 0.0,
            "CloseTodayRatioByVolume": value,
        }
    raise ValueError(f"unsupported fee unit: {notice['fee_unit']!r}")


def build_events(*, store_key: str = "openctp") -> list[dict[str, Any]]:
    hub = DataHub.get_instance()
    _ensure_store_registered(hub, store_key)
    provider = load_historical_field_provider(store_key=store_key)
    with hub.connect_store(store_key) as conn:
        ensure_agent_event_schema(conn)
        existing = _existing_keys(conn)
    events = [
        event
        for instrument, notice in LISTING_NOTICES.items()
        for field, value in _notice_fields(instrument, notice, provider=provider).items()
        if _event_key(event := _event(instrument, field, value, notice)) not in existing
    ]
    return events


def _notice_fields(instrument: str, notice: dict[str, Any], *, provider: Any | None = None) -> dict[str, float]:
    fields = dict(_fee_fields(notice))
    if "margin" in notice:
        fields["LongMarginRatioByMoney"] = float(notice["margin"])
        fields["ShortMarginRatioByMoney"] = float(notice["margin"])
    if "limit" in notice:
        fields["LimitUpDownRatio"] = float(notice["limit"])
    if "volume_multiple" in notice:
        fields["VolumeMultiple"] = float(notice["volume_multiple"])
    if "price_tick" in notice:
        fields["PriceTick"] = float(notice["price_tick"])
    if "inherits_from" in notice:
        if provider is None:
            raise ValueError(f"{instrument} requires a FieldHistory provider to materialize inherited rules")
        base_instrument = str(notice["inherits_from"])
        for field_name in ("LongMarginRatioByMoney", "ShortMarginRatioByMoney", "LimitUpDownRatio"):
            resolved = provider.resolve_by_trading_day(
                base_instrument,
                field_name,
                notice["effective_trading_day"],
                fallback=HistoricalFieldFallbackPolicy.STRICT_HISTORICAL,
            )
            fields[field_name] = float(resolved.value)
    return fields


def _field_group(field_name: str) -> str:
    if field_name in {"LongMarginRatioByMoney", "ShortMarginRatioByMoney"}:
        return "Margin"
    if field_name in {"LimitUpDownRatio", "VolumeMultiple", "PriceTick"}:
        return "TradingRules"
    return "TransactionFee"


def _event(instrument: str, field_name: str, value: float, notice: dict[str, Any]) -> dict[str, Any]:
    event_id = "field_history_" + hashlib.sha1(
        f"dce-listing:{instrument}:{field_name}:{notice['effective_trading_day']}:{value}".encode("utf-8")
    ).hexdigest()[:24]
    field_group = _field_group(field_name)
    is_inherited = field_group != "TransactionFee" and "inherits_from" in notice
    raw_note = notice["raw_note"] if field_group == "TransactionFee" else notice.get("rule_note", "")
    evidence = notice["raw_note"] + (" " + notice.get("rule_note", "") if notice.get("rule_note") else "")
    if is_inherited:
        evidence += (
            f" {instrument} inherits {field_name} from corresponding DCE product "
            f"{notice['inherits_from']} as of {notice['effective_trading_day']}."
        )
    return {
        "event_id": event_id,
        "data_source": "DCE",
        "field_group": field_group,
        "source_url": notice["source_url"],
        "source_accessed_at": "2026-07-09T00:00:00+08:00",
        "agent_name": "Agent:DCE",
        "requester_key": "field-history-official-dce-listing",
        "instrument": instrument,
        "instrument_label": notice["label"],
        "instrument_type": "future",
        "scope_type": "product",
        "exchange": "DCE",
        "field_name": field_name,
        "effective_trading_day": notice["effective_trading_day"],
        "effective_timestamp": notice["effective_timestamp"],
        "value": value,
        "contract_codes": [],
        "contract_scope_type": "all",
        "change_type": "baseline",
        "source_notice_id": notice["source_notice_id"],
        "raw_note": raw_note,
        "evidence_text": evidence,
        "parser_notes": (
            "Official DCE listing-notice baseline. Same-as-corresponding-contract "
            "rules are materialized as product-level listing baselines by resolving "
            "the corresponding product's FieldHistory value at the listing effective "
            "day; they are not exchange defaults. Hedge fee text is not mapped to "
            "normal fee fields."
        ),
    }


def _existing_keys(conn: sqlite3.Connection) -> set[tuple[Any, ...]]:
    return {
        tuple(row)
        for row in conn.execute(
            f"""
            SELECT data_source, field_group, instrument, instrument_type, field_name,
                   effective_trading_day, COALESCE(effective_timestamp, ''),
                   COALESCE(contract_scope_type, 'all'), contract_codes_json,
                   COALESCE(contract_code_start, ''), COALESCE(contract_code_end, ''),
                   value_json
            FROM {AGENT_EVENT_TABLE}
            WHERE data_source = 'DCE'
              AND field_group IN ('TransactionFee', 'Margin', 'TradingRules')
            """
        ).fetchall()
    }


def _listing_rows_to_fix(conn: sqlite3.Connection) -> list[sqlite3.Row]:
    notice_ids = tuple(notice["source_notice_id"] for notice in LISTING_NOTICES.values())
    return conn.execute(
        f"""
        SELECT event_id
        FROM {AGENT_EVENT_TABLE}
        WHERE data_source = 'DCE'
          AND field_group = 'TransactionFee'
          AND change_type != 'baseline'
          AND source_notice_id IN ({",".join("?" for _ in notice_ids)})
        """,
        notice_ids,
    ).fetchall()


def _mark_listing_rows_as_baseline(conn: sqlite3.Connection, event_ids: list[str]) -> None:
    if not event_ids:
        return
    conn.execute(
        f"""
        UPDATE {AGENT_EVENT_TABLE}
        SET change_type = 'baseline'
        WHERE event_id IN ({",".join("?" for _ in event_ids)})
        """,
        event_ids,
    )
    conn.execute(
        f"""
        UPDATE historical_field_values
        SET change_type = 'baseline'
        WHERE source_key IN ({",".join("?" for _ in event_ids)})
        """,
        event_ids,
    )
    conn.commit()


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

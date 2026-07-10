"""Ingest official exchange order-volume rule baselines.

This script only materializes order-volume facts that are stated directly by
exchange trading rules or listing notices.  It deliberately avoids margin,
price-limit, and fee fields because those require settlement-parameter tables or
product notices.
"""

from __future__ import annotations

import argparse
import hashlib
import json
from datetime import datetime
from typing import Any

from sources.FieldHistory.scripts.ingest_field_history_events import _rebuild_view
from tools.data.field_history import _ensure_store_registered
from tools.data.field_history_agent_ingest import (
    append_agent_field_change_events,
    ensure_agent_event_schema,
    materialize_agent_events_to_history,
)
from tools.data.hub import DataHub


EXCHANGE_DEFAULTS: tuple[dict[str, Any], ...] = (
    {
        "exchange": "SHFE",
        "effective_trading_day": "2024-01-02",
        "effective_timestamp": "2024-01-02 09:00:00",
        "source_url": "https://www.shfe.com.cn/regulation/exchangerules/historicalversion/202203/P020240320704141988177.doc",
        "source_notice_id": "SHFE-trading-rules-202203-order-volume-asof-20240102",
        "raw_note": "上海期货交易所交易细则：限价指令每次最大下单数量为500手；交易指令每次最小下单量为1手。2024边界时市价指令未作为期货默认指令上线。",
        "fields": {
            "MinLimitOrderVolume": 1.0,
            "MaxLimitOrderVolume": 500.0,
            "MaxMarketOrderVolume": 0.0,
        },
    },
    {
        "exchange": "INE",
        "effective_trading_day": "2024-01-02",
        "effective_timestamp": "2024-01-02 09:00:00",
        "source_url": "https://www.shfe.com.cn/regulation/ineregulation/businessmethods/trade/202606/t20260622_832193.html",
        "source_notice_id": "INE-trading-rules-order-volume-asof-20240102",
        "raw_note": "上海国际能源交易中心交易细则：交易指令每次最小下单数量为1手，每次最大下单数量为500手，能源中心另有规定的除外。2024边界时市价指令未作为期货默认指令上线。",
        "fields": {
            "MinLimitOrderVolume": 1.0,
            "MaxLimitOrderVolume": 500.0,
            "MaxMarketOrderVolume": 0.0,
        },
    },
    {
        "exchange": "CFFEX",
        "effective_trading_day": "2024-01-02",
        "effective_timestamp": "2024-01-02 09:30:00",
        "source_url": "https://www.cffex.com.cn/u/cms/www/oldsys/P020100824638757075349.doc",
        "source_notice_id": "CFFEX-trading-rules-order-volume-asof-20240102",
        "raw_note": "中国金融期货交易所交易细则：交易指令每次最小下单数量为1手，市价指令每次最大下单数量为50手，限价指令每次最大下单数量为100手。",
        "fields": {
            "MinLimitOrderVolume": 1.0,
            "MaxLimitOrderVolume": 100.0,
            "MaxMarketOrderVolume": 50.0,
        },
    },
    {
        "exchange": "SHFE",
        "effective_trading_day": "2026-07-06",
        "effective_timestamp": "2026-07-03 21:00:00",
        "source_url": "https://www.shfe.com.cn/",
        "source_notice_id": "上期发〔2026〕242号",
        "raw_note": "关于市价指令上线及有关交易指令下单量的通知：自2026年7月6日（即2026年7月3日晚连续交易时段）起，限价指令每次最小下单量为1手，最大下单量期货品种为500手；市价指令每次最小下单量为1手，最大下单量期货品种为60手。",
        "fields": {
            "MinLimitOrderVolume": 1.0,
            "MaxLimitOrderVolume": 500.0,
            "MaxMarketOrderVolume": 60.0,
        },
    },
    {
        "exchange": "INE",
        "effective_trading_day": "2026-07-06",
        "effective_timestamp": "2026-07-03 21:00:00",
        "source_url": "https://www.ine.cn/regulation/ineregulation/rules/202606/t20260622_832198.html",
        "source_notice_id": "上能发〔2026〕73号",
        "raw_note": "关于市价指令上线及有关交易指令下单量的通知：自2026年7月6日（即2026年7月3日晚连续交易时段）起，限价指令每次最小下单量为1手，最大下单量期货品种为500手；市价指令每次最小下单量为1手，最大下单量期货品种为60手。",
        "fields": {
            "MinLimitOrderVolume": 1.0,
            "MaxLimitOrderVolume": 500.0,
            "MaxMarketOrderVolume": 60.0,
        },
    },
)


PRODUCT_BASELINES: tuple[dict[str, Any], ...] = (
    {
        "exchange": "CZCE",
        "instrument": "PR",
        "instrument_label": "瓶片",
        "effective_trading_day": "2024-08-30",
        "effective_timestamp": "2024-08-30 09:00:00",
        "source_url": "https://www.czce.com.cn/",
        "source_notice_id": "CZCE-PR-listing-order-volume-20240830",
        "raw_note": "瓶片期货合约交易指令每次最小下单量为1手，限价指令每次最大下单量为1000手，市价指令每次最大下单量为200手。",
        "fields": {
            "MinLimitOrderVolume": 1.0,
            "MaxLimitOrderVolume": 1000.0,
            "MaxMarketOrderVolume": 200.0,
        },
    },
    {
        "exchange": "CZCE",
        "instrument": "PL",
        "instrument_label": "丙烯",
        "effective_trading_day": "2025-07-22",
        "effective_timestamp": "2025-07-22 09:00:00",
        "source_url": "https://www.czce.com.cn/cn/sspz/bxqhqq/bzhy/qhhy/H077002030002001index_1.htm",
        "source_notice_id": "CZCE-PL-listing-order-volume-20250722",
        "raw_note": "丙烯期货合约交易指令每次最小下单量为1手，限价指令每次最大下单量为1000手，市价指令每次最大下单量为200手。",
        "fields": {
            "MinLimitOrderVolume": 1.0,
            "MaxLimitOrderVolume": 1000.0,
            "MaxMarketOrderVolume": 200.0,
        },
    },
)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--store-key", default="openctp")
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args(argv)

    events = build_events(store_key=args.store_key)
    corrected_alias_rows = 0 if args.dry_run else _sync_exchange_default_aliases(store_key=args.store_key)
    print(json.dumps({
        "candidate_events": len(events),
        "inserted": 0 if args.dry_run else len(events),
        "corrected_alias_rows": corrected_alias_rows,
        "sample_event_ids": [event["event_id"] for event in events[:30]],
    }, ensure_ascii=False, indent=2))
    if args.dry_run or not events:
        if corrected_alias_rows:
            _rebuild_view("TradingRules", store_key=args.store_key)
        return 0
    append_agent_field_change_events(events, store_key=args.store_key)
    materialize_agent_events_to_history(store_key=args.store_key, field_group="TradingRules")
    _rebuild_view("TradingRules", store_key=args.store_key)
    return 0


def build_events(*, store_key: str = "openctp") -> list[dict[str, Any]]:
    hub = DataHub.get_instance()
    _ensure_store_registered(hub, store_key)
    accessed_at = datetime.now().astimezone().isoformat(timespec="seconds")
    with hub.connect_store(store_key) as conn:
        ensure_agent_event_schema(conn)
        existing = _existing_keys(conn)
    events = [
        event
        for source in EXCHANGE_DEFAULTS
        for field_name, value in source["fields"].items()
        if _event_key(event := _exchange_default_event(source, field_name, value, accessed_at=accessed_at)) not in existing
    ]
    events.extend(
        event
        for source in PRODUCT_BASELINES
        for field_name, value in source["fields"].items()
        if _event_key(event := _product_event(source, field_name, value, accessed_at=accessed_at)) not in existing
    )
    return events


def _existing_keys(conn: Any) -> set[tuple[Any, ...]]:
    return {
        tuple(row)
        for row in conn.execute(
            """
            SELECT data_source, field_group, instrument, instrument_type, field_name,
                   effective_trading_day, COALESCE(effective_timestamp, ''),
                   COALESCE(contract_scope_type, 'all'), contract_codes_json,
                   COALESCE(contract_code_start, ''), COALESCE(contract_code_end, ''),
                   value_json
            FROM agent_field_change_events
            WHERE field_group = 'TradingRules'
            """
        ).fetchall()
    }


def _sync_exchange_default_aliases(*, store_key: str) -> int:
    hub = DataHub.get_instance()
    _ensure_store_registered(hub, store_key)
    corrected = 0
    with hub.connect_store(store_key) as conn:
        ensure_agent_event_schema(conn)
        for long_name, alias in {"SHFE": "SHF", "CFFEX": "CFE", "GFEX": "GFE", "CZCE": "CZC"}.items():
            for table, key_column in (("agent_field_change_events", "event_id"), ("historical_field_values", "source_key")):
                if table == "agent_field_change_events":
                    cursor = conn.execute(
                        f"""
                        UPDATE {table}
                        SET exchange = ?
                        WHERE data_source = ?
                          AND field_group = 'TradingRules'
                          AND instrument = '*'
                          AND scope_type = 'exchange_default'
                          AND exchange = ?
                        """,
                        (alias, long_name, long_name),
                    )
                else:
                    cursor = conn.execute(
                        f"""
                        UPDATE {table}
                        SET exchange = ?
                        WHERE provider = ?
                          AND instrument = '*'
                          AND scope_type = 'exchange_default'
                          AND exchange = ?
                        """,
                        (alias, f"Agent:{long_name}", long_name),
                    )
                corrected += int(cursor.rowcount or 0)
        conn.commit()
    return corrected


def _exchange_default_event(source: dict[str, Any], field_name: str, value: float, *, accessed_at: str) -> dict[str, Any]:
    exchange = str(source["exchange"])
    exchange_alias = _field_history_exchange_alias(exchange)
    event_id = _event_id("exchange-default", exchange_alias, field_name, source["effective_trading_day"], value)
    return _base_event(
        event_id=event_id,
        data_source=exchange,
        exchange=exchange_alias,
        instrument="*",
        instrument_label=f"{exchange}期货交易指令默认规则",
        scope_type="exchange_default",
        field_name=field_name,
        value=value,
        source=source,
        accessed_at=accessed_at,
        change_type="asof_confirmed" if source["effective_trading_day"] == "2024-01-02" else "change",
    )


def _product_event(source: dict[str, Any], field_name: str, value: float, *, accessed_at: str) -> dict[str, Any]:
    event_id = _event_id("product-baseline", source["instrument"], field_name, source["effective_trading_day"], value)
    return _base_event(
        event_id=event_id,
        data_source=str(source["exchange"]),
        exchange=str(source["exchange"]),
        instrument=str(source["instrument"]),
        instrument_label=str(source["instrument_label"]),
        scope_type="product",
        field_name=field_name,
        value=value,
        source=source,
        accessed_at=accessed_at,
        change_type="baseline",
    )


def _base_event(
    *,
    event_id: str,
    data_source: str,
    exchange: str,
    instrument: str,
    instrument_label: str,
    scope_type: str,
    field_name: str,
    value: float,
    source: dict[str, Any],
    accessed_at: str,
    change_type: str,
) -> dict[str, Any]:
    return {
        "event_id": event_id,
        "data_source": data_source,
        "field_group": "TradingRules",
        "source_url": source["source_url"],
        "source_accessed_at": accessed_at,
        "agent_name": f"Agent:{data_source}",
        "requester_key": "field-history-official-order-volume-rules",
        "instrument": instrument,
        "instrument_label": instrument_label,
        "instrument_type": "future",
        "scope_type": scope_type,
        "exchange": exchange,
        "field_name": field_name,
        "effective_trading_day": source["effective_trading_day"],
        "effective_timestamp": source["effective_timestamp"],
        "value": value,
        "contract_codes": [],
        "contract_scope_type": "all",
        "change_type": change_type,
        "source_notice_id": source["source_notice_id"],
        "raw_note": source["raw_note"],
        "evidence_text": source["raw_note"],
        "parser_notes": (
            "Order-volume rule event generated from exchange trading rules or "
            "listing notices.  MaxMarketOrderVolume=0 means market orders were "
            "not available as an ordinary futures order type at that boundary."
        ),
    }


def _event_id(prefix: str, subject: str, field_name: str, day: str, value: float) -> str:
    digest = hashlib.sha1(f"{prefix}:{subject}:{field_name}:{day}:{value:g}".encode("utf-8")).hexdigest()[:24]
    return f"field_history_order_volume_{digest}"


def _field_history_exchange_alias(exchange: str) -> str:
    return {
        "CFFEX": "CFE",
        "CZCE": "CZC",
        "DCE": "DCE",
        "GFEX": "GFE",
        "INE": "INE",
        "SHFE": "SHF",
    }[exchange]


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

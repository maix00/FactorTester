"""Ingest DCE official order-volume baselines for known 2024+ gaps.

CSRC's rules database is the preferred source.  The products below were probed
there first but were not returned by the rules-db search API, while DCE official
business-rule pages state the order-volume text directly.  This script keeps the
scope narrow to those verified DCE order-volume facts.
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


SOURCE_NAME = "DCE"

_DCE_MAX_1000_NOTE = (
    "DCE official business rule states: 交易指令每次最大下单数量为1000手. "
    "Project convention materializes this generic trading-instruction maximum "
    "to both MaxLimitOrderVolume and MaxMarketOrderVolume."
)


OFFICIAL_LIMIT_ORDER_BASELINES: tuple[dict[str, Any], ...] = (
    {
        "instrument": "L",
        "instrument_label": "线型低密度聚乙烯",
        "effective_trading_day": "2024-01-02",
        "effective_timestamp": "2024-01-02 09:00:00",
        "change_type": "asof_confirmed",
        "source_url": "http://www.dce.com.cn/dce/content/2018/pzxz/6146536.html",
        "source_notice_id": "DCE-L-business-rule",
        "raw_note": "线型低密度聚乙烯期货合约的交易指令每次最大下单数量为1000手。",
        "fields": {"MaxLimitOrderVolume": 1000.0, "MaxMarketOrderVolume": 1000.0},
    },
    {
        "instrument": "BZ",
        "instrument_label": "纯苯",
        "effective_trading_day": "2025-07-08",
        "effective_timestamp": "2025-07-08 09:00:00",
        "change_type": "baseline",
        "source_url": "http://www.dce.com.cn/dce/content/2025/pzxz/8637789.html",
        "source_notice_id": "DCE-BZ-business-rule",
        "raw_note": "纯苯期货合约的交易指令每次最大下单数量为1000手。",
        "fields": {
            "MinLimitOrderVolume": 1.0,
            "MaxLimitOrderVolume": 1000.0,
            "MaxMarketOrderVolume": 1000.0,
        },
    },
    {
        "instrument": "LG",
        "instrument_label": "原木",
        "effective_trading_day": "2024-11-18",
        "effective_timestamp": "2024-11-18 09:00:00",
        "change_type": "baseline",
        "source_url": "http://www.dce.com.cn/dce/content/2024/pzxz/8617210.html",
        "source_notice_id": "DCE-LG-business-rule",
        "raw_note": "原木期货合约的交易指令每次最大下单数量为1000手。",
        "fields": {
            "MinLimitOrderVolume": 1.0,
            "MaxLimitOrderVolume": 1000.0,
            "MaxMarketOrderVolume": 1000.0,
        },
    },
    {
        "instrument": "L_F",
        "instrument_label": "聚乙烯月均价期货",
        "effective_trading_day": "2025-10-29",
        "effective_timestamp": "2025-10-28 21:00:00",
        "change_type": "baseline",
        "source_url": "http://www.dce.com.cn/dce/content/2025/pzxz/18619200.html",
        "source_notice_id": "大商所发〔2025〕367号",
        "raw_note": "线型低密度聚乙烯月均价期货合约的交易指令每次最大下单数量为1000手。",
        "fields": {
            "MinLimitOrderVolume": 1.0,
            "MaxLimitOrderVolume": 1000.0,
            "MaxMarketOrderVolume": 1000.0,
        },
    },
    {
        "instrument": "PP_F",
        "instrument_label": "聚丙烯月均价期货",
        "effective_trading_day": "2025-10-29",
        "effective_timestamp": "2025-10-28 21:00:00",
        "change_type": "baseline",
        "source_url": "http://www.dce.com.cn/dce/content/2025/pzxz/18619208.html",
        "source_notice_id": "大商所发〔2025〕367号",
        "raw_note": "聚丙烯月均价期货合约的交易指令每次最大下单数量为1000手。",
        "fields": {
            "MinLimitOrderVolume": 1.0,
            "MaxLimitOrderVolume": 1000.0,
            "MaxMarketOrderVolume": 1000.0,
        },
    },
    {
        "instrument": "V_F",
        "instrument_label": "聚氯乙烯月均价期货",
        "effective_trading_day": "2025-10-29",
        "effective_timestamp": "2025-10-28 21:00:00",
        "change_type": "baseline",
        "source_url": "http://www.dce.com.cn/dce/content/2025/pzxz/18619205.html",
        "source_notice_id": "大商所发〔2025〕367号",
        "raw_note": "聚氯乙烯月均价期货合约的交易指令每次最大下单数量为1000手。",
        "fields": {
            "MinLimitOrderVolume": 1.0,
            "MaxLimitOrderVolume": 1000.0,
            "MaxMarketOrderVolume": 1000.0,
        },
    },
)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--store-key", default="openctp")
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args(argv)

    _ensure_store_registered(DataHub.get_instance(), args.store_key)
    events = build_events(store_key=args.store_key)
    print(json.dumps({
        "candidate_events_after_dedupe": len(events),
        "sample_event_ids": [event["event_id"] for event in events[:20]],
    }, ensure_ascii=False, indent=2))
    if args.dry_run or not events:
        return 0
    append_agent_field_change_events(events, store_key=args.store_key)
    materialize_agent_events_to_history(store_key=args.store_key, data_source=SOURCE_NAME, field_group="LimitOrderVolume")
    _rebuild_view("LimitOrderVolume", store_key=args.store_key)
    return 0


def build_events(*, store_key: str = "openctp") -> list[dict[str, Any]]:
    with DataHub.get_instance().connect_store(store_key) as conn:
        ensure_agent_event_schema(conn)
        existing = {
            str(row[0])
            for row in conn.execute(
                "SELECT event_id FROM agent_field_change_events WHERE data_source = ?",
                (SOURCE_NAME,),
            ).fetchall()
        }
    accessed_at = datetime.now().astimezone().isoformat(timespec="seconds")
    events: list[dict[str, Any]] = []
    for source in OFFICIAL_LIMIT_ORDER_BASELINES:
        for field_name, value in source["fields"].items():
            event = _event(source, field_name, float(value), accessed_at=accessed_at)
            if event["event_id"] not in existing:
                events.append(event)
    return events


def _event(source: dict[str, Any], field_name: str, value: float, *, accessed_at: str) -> dict[str, Any]:
    event_id = "field_history_dce_official_limit_order_" + hashlib.sha1(
        (
            f"{source['instrument']}:{field_name}:{source['effective_trading_day']}:"
            f"{value}:{source['source_notice_id']}:{source['source_url']}"
        ).encode("utf-8")
    ).hexdigest()[:24]
    return {
        "event_id": event_id,
        "data_source": SOURCE_NAME,
        "field_group": "LimitOrderVolume",
        "source_url": source["source_url"],
        "source_accessed_at": accessed_at,
        "agent_name": "Agent:DCE",
        "requester_key": "field-history-dce-official-limit-order-baselines",
        "instrument": source["instrument"],
        "instrument_label": source["instrument_label"],
        "instrument_type": "future",
        "scope_type": "product",
        "exchange": "DCE",
        "field_name": field_name,
        "effective_trading_day": source["effective_trading_day"],
        "effective_timestamp": source["effective_timestamp"],
        "value": value,
        "contract_codes": [],
        "contract_scope_type": "all",
        "change_type": source["change_type"],
        "source_notice_id": source["source_notice_id"],
        "raw_note": source["raw_note"],
        "evidence_text": source["raw_note"],
        "parser_notes": (
            f"{_DCE_MAX_1000_NOTE} CSRC rules database was probed first for this gap; "
            "the relevant DCE official page was used when CSRC search returned no matching business-rule version."
        ),
    }


if __name__ == "__main__":
    raise SystemExit(main())

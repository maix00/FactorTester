"""Ingest DCE 2023 base margin and price-limit adjustment notice.

The original DCE page is currently protected by anti-bot checks in this
environment.  The source URL below is a notice-preserving repost that keeps the
exchange notice id, issuer, date, and full adjustment text.  Replace it with
the DCE original URL once it can be fetched reliably.
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


NOTICE = {
    "source_url": "https://www.bhfcc.com/customer-center-ques-details.html?id=8899",
    "source_notice_id": "大商所发〔2023〕139号",
    "source_accessed_at": "2026-07-09T00:00:00+08:00",
    "effective_trading_day": "2023-04-13",
    "effective_timestamp": "2023-04-12 15:00:00",
    "raw_note": (
        "根据大连商品交易所《关于调整棕榈油等期货合约涨跌停板幅度和交易保证金水平的通知》"
        "大商所发〔2023〕139号：自2023年4月12日结算时起，棕榈油、乙二醇、苯乙烯和"
        "液化石油气期货合约涨跌停板幅度调整为7%，交易保证金水平调整为8%；豆粕、豆油、"
        "聚乙烯、聚丙烯、聚氯乙烯期货合约涨跌停板幅度调整为6%，交易保证金水平调整为7%；"
        "玉米淀粉期货合约涨跌停板幅度调整为5%，交易保证金水平调整为6%；其他期货合约"
        "涨跌停板幅度和交易保证金水平维持不变。"
    ),
    "parser_notes": (
        "Notice-preserving repost of DCE notice 大商所发〔2023〕139号. "
        "This event stores only base/normal margin and price-limit fields explicitly adjusted by the notice. "
        "DCE deterministic delivery-calendar overlays are expanded separately into resolved FieldHistory "
        "contract rows; path-dependent limit-move, holiday, position-size, hedge, and combination-margin "
        "overlays are outside this base-notice event. "
        "The notice effective phrase is settlement on 2023-04-12; the value is "
        "therefore effective for trading day 2023-04-13."
    ),
}

PRODUCTS: dict[str, tuple[str, float, float]] = {
    "P": ("棕榈油", 0.08, 0.07),
    "EG": ("乙二醇", 0.08, 0.07),
    "EB": ("苯乙烯", 0.08, 0.07),
    "PG": ("液化石油气", 0.08, 0.07),
    "M": ("豆粕", 0.07, 0.06),
    "Y": ("豆油", 0.07, 0.06),
    "L": ("聚乙烯", 0.07, 0.06),
    "PP": ("聚丙烯", 0.07, 0.06),
    "V": ("聚氯乙烯", 0.07, 0.06),
    "CS": ("玉米淀粉", 0.06, 0.05),
}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--store-key", default="openctp")
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args(argv)

    events = build_events(store_key=args.store_key)
    print(json.dumps({
        "candidate_events": len(events),
        "inserted": 0 if args.dry_run else len(events),
        "sample_event_ids": [event["event_id"] for event in events[:20]],
    }, ensure_ascii=False, indent=2))
    if args.dry_run or not events:
        return 0
    append_agent_field_change_events(events, store_key=args.store_key)
    for field_group in {"Margin", "TradingRules"}:
        materialize_agent_events_to_history(store_key=args.store_key, data_source="DCE", field_group=field_group)
        _rebuild_view(field_group, store_key=args.store_key)
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
                WHERE data_source = 'DCE'
                  AND field_group IN ('Margin', 'TradingRules')
                """
            ).fetchall()
        }
    events = [
        event
        for instrument, (label, margin, limit) in PRODUCTS.items()
        for field_name, value in (
            ("LongMarginRatioByMoney", margin),
            ("ShortMarginRatioByMoney", margin),
            ("LimitUpDownRatio", limit),
        )
        if _event_key(event := _event(instrument, label, field_name, value)) not in existing
    ]
    return events


def _field_group(field_name: str) -> str:
    if field_name in {"LongMarginRatioByMoney", "ShortMarginRatioByMoney"}:
        return "Margin"
    if field_name == "LimitUpDownRatio":
        return "TradingRules"
    raise ValueError(f"unsupported field: {field_name}")


def _event(instrument: str, label: str, field_name: str, value: float) -> dict[str, Any]:
    event_id = "field_history_" + hashlib.sha1(
        (
            f"dce-2023-139:{instrument}:{field_name}:"
            f"{NOTICE['effective_trading_day']}:{value}"
        ).encode("utf-8")
    ).hexdigest()[:24]
    return {
        "event_id": event_id,
        "data_source": "DCE",
        "field_group": _field_group(field_name),
        "source_url": NOTICE["source_url"],
        "source_accessed_at": NOTICE["source_accessed_at"],
        "agent_name": "Agent:DCE",
        "requester_key": "field-history-official-dce-margin-limit",
        "instrument": instrument,
        "instrument_label": label,
        "instrument_type": "future",
        "scope_type": "product",
        "exchange": "DCE",
        "field_name": field_name,
        "effective_trading_day": NOTICE["effective_trading_day"],
        "effective_timestamp": NOTICE["effective_timestamp"],
        "value": value,
        "contract_codes": [],
        "contract_scope_type": "all",
        "change_type": "change",
        "source_notice_id": NOTICE["source_notice_id"],
        "raw_note": NOTICE["raw_note"],
        "evidence_text": NOTICE["raw_note"],
        "parser_notes": NOTICE["parser_notes"],
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

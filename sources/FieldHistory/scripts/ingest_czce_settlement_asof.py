"""Ingest CZCE official settlement-parameter TXT as 2024-boundary as-of rows."""

from __future__ import annotations

import argparse
import math
import re
from collections import defaultdict
from datetime import datetime
from typing import Any
from urllib.request import Request, urlopen

from tools.data.field_history_agent_ingest import (
    append_agent_field_change_events,
    ensure_agent_event_schema,
    materialize_agent_events_to_history,
)
from tools.data.field_history import _ensure_store_registered
from tools.data.hub import DataHub


OFFICIAL_URL_TEMPLATE = "https://www.czce.com.cn/cn/DFSStaticFiles/Future/{year}/{date}/FutureDataClearParams.txt"
FIELDS = (
    "OpenRatioByMoney",
    "CloseRatioByMoney",
    "CloseTodayRatioByMoney",
    "OpenRatioByVolume",
    "CloseRatioByVolume",
    "CloseTodayRatioByVolume",
    "LongMarginRatioByMoney",
    "ShortMarginRatioByMoney",
    "LimitUpDownRatio",
)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--date", required=True, help="Official snapshot date, e.g. 20240102")
    parser.add_argument("--store-key", default="openctp")
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args(argv)
    _ensure_store_registered(DataHub.get_instance(), args.store_key)

    events = build_events(date=args.date)
    events = _skip_existing(events, store_key=args.store_key)
    print("CZCE official settlement as-of ingestion")
    print(f"  date: {args.date}")
    print(f"  candidate_events_after_dedupe: {len(events)}")
    by_field: dict[str, int] = defaultdict(int)
    for event in events:
        by_field[str(event["field_name"])] += 1
    for field, count in sorted(by_field.items()):
        print(f"    {field}: {count}")
    if args.dry_run or not events:
        return 0
    append_agent_field_change_events(events, store_key=args.store_key)
    for field_group in {"TransactionFee", "Margin", "TradingRules"}:
        materialize_agent_events_to_history(store_key=args.store_key, data_source="CZCE", field_group=field_group)
    _rebuild_views(store_key=args.store_key)
    print("  inserted/materialized/rebuilt")
    return 0


def build_events(*, date: str) -> list[dict[str, Any]]:
    text = _fetch_snapshot(date)
    rows = _parse_snapshot_text(text)
    snapshot_day = _date8_to_iso(date)
    source_url = OFFICIAL_URL_TEMPLATE.format(year=date[:4], date=date)
    source_notice_id = f"CZCE-FutureDataClearParams-{date}-asof-confirmed"
    accessed_at = datetime.now().astimezone().isoformat(timespec="seconds")

    grouped: dict[tuple[str, str, float], list[str]] = defaultdict(list)
    product_symbols: dict[str, set[str]] = defaultdict(set)
    for row in rows:
        symbol = str(row["合约代码"]).strip().upper()
        product = _product_from_symbol(symbol)
        product_symbols[product].add(symbol)
        values = _values_from_row(row)
        for field, value in values.items():
            if value is None:
                continue
            grouped[(product, field, float(value))].append(symbol)

    events: list[dict[str, Any]] = []
    by_product_field: dict[tuple[str, str], dict[float, list[str]]] = defaultdict(dict)
    for (product, field, value), symbols in grouped.items():
        by_product_field[(product, field)][value] = sorted(set(symbols))

    for (product, field), value_symbols_by_value in sorted(by_product_field.items()):
        all_symbols = sorted(product_symbols[product])
        base_value = _product_level_asof_value(value_symbols_by_value)
        events.append(_event(
            date=date,
            product=product,
            field=field,
            value=base_value,
            symbols=[],
            scope_type="all",
            snapshot_day=snapshot_day,
            source_url=source_url,
            source_notice_id=source_notice_id,
            accessed_at=accessed_at,
        ))
        for value, symbols in sorted(value_symbols_by_value.items()):
            if value == base_value:
                continue
            events.append(_event(
                date=date,
                product=product,
                field=field,
                value=value,
                symbols=symbols,
                scope_type="explicit",
                snapshot_day=snapshot_day,
                source_url=source_url,
                source_notice_id=source_notice_id,
                accessed_at=accessed_at,
            ))
    return events


def _product_level_asof_value(value_symbols_by_value: dict[float, list[str]]) -> float:
    """Choose the product-level as-of value before explicit contract overrides.

    Official settlement snapshots are contract rows.  For phase-1 coverage we
    still need a product-level confirmation anchor, but contract-specific
    differences must remain visible and override it.  The product-level value is
    therefore the most common contract value; ties are resolved deterministically
    by the numeric value so ingestion is stable.
    """
    if not value_symbols_by_value:
        raise ValueError("cannot choose product-level as-of value from empty snapshot group")
    return sorted(value_symbols_by_value, key=lambda value: (-len(value_symbols_by_value[value]), value))[0]


def _event(
    *,
    date: str,
    product: str,
    field: str,
    value: float,
    symbols: list[str],
    scope_type: str,
    snapshot_day: str,
    source_url: str,
    source_notice_id: str,
    accessed_at: str,
) -> dict[str, Any]:
    event_id = _event_id(date, product, field, value, [] if scope_type == "all" else symbols)
    return {
        "event_id": event_id,
        "data_source": "CZCE",
        "field_group": _field_group(field),
        "source_url": source_url,
        "source_accessed_at": accessed_at,
        "agent_name": "Codex",
        "requester_key": "side-conversation-issue-124",
        "instrument": product,
        "instrument_label": product,
        "instrument_type": "future",
        "scope_type": "product",
        "exchange": "CZC",
        "field_name": field,
        "effective_trading_day": snapshot_day,
        "effective_timestamp": f"{snapshot_day} 09:00:00",
        "value": value,
        "contract_scope_type": scope_type,
        "contract_codes": [] if scope_type == "all" else symbols,
        "change_type": "asof_confirmed",
        "source_notice_id": source_notice_id,
        "raw_note": (
            f"郑州商品交易所期货结算参数表({snapshot_day}) official TXT. "
            "Used only as 2024-boundary as-of confirmation, not as listing baseline."
        ),
        "evidence_text": "Columns: 交易保证金率(%), 涨跌停板(%), 交易手续费, 手续费收取方式, 日内平今仓交易手续费.",
        "parser_notes": (
            "绝对值 maps to *RatioByVolume and inactive *RatioByMoney=0; "
            "比例值 maps to *RatioByMoney/10000 and inactive *RatioByVolume=0. "
            "For products with contract-level differences, the product-level "
            "as-of value is the most common contract value and explicit "
            "contract rows override it. Post-boundary changes still require "
            "normal exchange-notice change events."
        ),
    }


def _fetch_snapshot(date: str) -> str:
    url = OFFICIAL_URL_TEMPLATE.format(year=date[:4], date=date)
    request = Request(
        url,
        headers={
            "User-Agent": "Mozilla/5.0",
            "Referer": "https://www.czce.com.cn/cn/jysj/jscs/H077003003index_1.htm",
        },
    )
    with urlopen(request, timeout=30) as response:
        return response.read().decode("utf-8-sig")


def _parse_snapshot_text(text: str) -> list[dict[str, str]]:
    lines = [line.strip() for line in text.splitlines() if line.strip()]
    header_index = next(i for i, line in enumerate(lines) if "合约代码|" in line)
    headers = [part.strip() for part in lines[header_index].split("|")]
    rows: list[dict[str, str]] = []
    for line in lines[header_index + 1:]:
        parts = [part.strip() for part in line.split("|")]
        if len(parts) < len(headers):
            parts += [""] * (len(headers) - len(parts))
        row = dict(zip(headers, parts, strict=False))
        if row.get("合约代码"):
            rows.append(row)
    return rows


def _values_from_row(row: dict[str, str]) -> dict[str, float | None]:
    fee_type = row.get("手续费收取方式", "")
    trade_fee = _parse_float(row.get("交易手续费"))
    close_today_fee = _parse_float(row.get("日内平今仓交易手续费"))
    if fee_type == "绝对值":
        values: dict[str, float | None] = {
            "OpenRatioByMoney": 0.0,
            "CloseRatioByMoney": 0.0,
            "CloseTodayRatioByMoney": 0.0,
            "OpenRatioByVolume": trade_fee,
            "CloseRatioByVolume": trade_fee,
            "CloseTodayRatioByVolume": close_today_fee,
        }
    elif fee_type == "比例值":
        values = {
            "OpenRatioByMoney": None if trade_fee is None else trade_fee / 10000.0,
            "CloseRatioByMoney": None if trade_fee is None else trade_fee / 10000.0,
            "CloseTodayRatioByMoney": None if close_today_fee is None else close_today_fee / 10000.0,
            "OpenRatioByVolume": 0.0,
            "CloseRatioByVolume": 0.0,
            "CloseTodayRatioByVolume": 0.0,
        }
    else:
        values = {}
    margin = _percent_value(row.get("交易保证金率(%)"))
    limit = _percent_value(row.get("涨跌停板(%)"))
    values.update({
        "LongMarginRatioByMoney": margin,
        "ShortMarginRatioByMoney": margin,
        "LimitUpDownRatio": limit,
    })
    return values


def _parse_float(value: Any) -> float | None:
    text = str(value or "").strip().replace(",", "")
    if not text:
        return None
    try:
        result = float(text)
    except ValueError:
        return None
    return None if math.isnan(result) else result


def _percent_value(value: Any) -> float | None:
    text = str(value or "").replace("±", "").replace("%", "").strip()
    parsed = _parse_float(text)
    if parsed is None:
        return None
    return parsed / 100.0 if parsed > 1 else parsed


def _product_from_symbol(symbol: str) -> str:
    match = re.match(r"([A-Z]+)", symbol.upper())
    if not match:
        raise ValueError(f"cannot parse CZCE product from symbol={symbol!r}")
    return match.group(1)


def _field_group(field: str) -> str:
    if field in {"LongMarginRatioByMoney", "ShortMarginRatioByMoney"}:
        return "Margin"
    if field == "LimitUpDownRatio":
        return "TradingRules"
    return "TransactionFee"


def _event_id(date: str, product: str, field: str, value: float, symbols: list[str]) -> str:
    safe_value = re.sub(r"[^0-9a-zA-Z]+", "_", f"{value:g}").strip("_")
    suffix = "" if not symbols else "_" + "_".join(symbols)
    return f"czce_future_data_clear_params_{date}_{product}_{field}_{safe_value}{suffix}".lower()


def _date8_to_iso(value: str) -> str:
    return f"{value[:4]}-{value[4:6]}-{value[6:8]}"


def _skip_existing(events: list[dict[str, Any]], *, store_key: str) -> list[dict[str, Any]]:
    if not events:
        return []
    hub = DataHub.get_instance()
    with hub.connect_store(store_key) as conn:
        ensure_agent_event_schema(conn)
        existing = {
            str(row["event_id"])
            for row in conn.execute(
                "SELECT event_id FROM agent_field_change_events WHERE event_id IN ({})".format(
                    ",".join("?" for _ in events)
                ),
                [event["event_id"] for event in events],
            ).fetchall()
        }
    return [event for event in events if str(event["event_id"]) not in existing]


def _rebuild_views(*, store_key: str) -> None:
    from sources.FieldHistory.views.Unified import save_unified_table as save_unified
    from sources.FieldHistory.views.TransactionFee import save_unified_table as save_fee

    save_unified(store_key=store_key)
    save_fee(store_key=store_key)


if __name__ == "__main__":
    raise SystemExit(main())

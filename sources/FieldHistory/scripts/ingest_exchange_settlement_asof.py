"""Ingest official exchange settlement snapshots as phase-1 as-of rows.

This script intentionally uses exchange-owned endpoints only.  Broker,
OpenCTP, AKShare, or futures-company snapshots may be used for audit clues, but
must not be ingested here as exchange rules.
"""

from __future__ import annotations

import argparse
import csv
import io
import math
import re
from collections import defaultdict
from datetime import datetime
from pathlib import Path
from typing import Any

import requests

from tools.data.field_history import _ensure_store_registered
from tools.data.field_history_agent_ingest import (
    append_agent_field_change_events,
    ensure_agent_event_schema,
    materialize_agent_events_to_history,
)
from tools.data.hub import DataHub


HEADERS = {"User-Agent": "Mozilla/5.0"}
SHFE_LIKE = {"SHFE", "INE"}
INE_INSTRUMENTS = {"BC", "EC", "LU", "NR", "SC"}
CFFEX_FUTURES = {"IC", "IF", "IH", "IM", "T", "TF", "TL", "TS"}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--date", required=True, help="Official snapshot date, e.g. 20240102")
    parser.add_argument("--market", action="append", choices=("DCE", "SHFE", "INE", "GFEX", "CFFEX"), default=[])
    parser.add_argument(
        "--dce-csv",
        action="append",
        default=[],
        help=(
            "Manually downloaded DCE settlement-parameter CSV. May be repeated. "
            "DCE CSV rows are official as-of settlement parameters and are ingested as asof_confirmed anchors."
        ),
    )
    parser.add_argument("--store-key", default="openctp")
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args(argv)
    _ensure_store_registered(DataHub.get_instance(), args.store_key)

    markets = args.market or ["SHFE", "INE", "GFEX"]
    dce_csv_by_date = _dce_csv_by_date(args.dce_csv)
    events: list[dict[str, Any]] = []
    for market in markets:
        events.extend(build_events(market=market, date=args.date, dce_csv_by_date=dce_csv_by_date))
    events = _skip_existing(events, store_key=args.store_key)
    print("Official exchange settlement as-of ingestion")
    print(f"  date: {args.date}")
    print(f"  markets: {','.join(markets)}")
    print(f"  candidate_events_after_dedupe: {len(events)}")
    by_market_field: dict[tuple[str, str], int] = defaultdict(int)
    for event in events:
        by_market_field[(str(event["data_source"]), str(event["field_name"]))] += 1
    for (market, field), count in sorted(by_market_field.items()):
        print(f"    {market} {field}: {count}")
    if args.dry_run or not events:
        return 0
    append_agent_field_change_events(events, store_key=args.store_key)
    for field_group in {"TransactionFee", "Margin"}:
        materialize_agent_events_to_history(store_key=args.store_key, data_source="", field_group=field_group)
    _rebuild_views(store_key=args.store_key)
    print("  inserted/materialized/rebuilt")
    return 0


def build_events(
    *,
    market: str,
    date: str,
    dce_csv_by_date: dict[str, Any] | None = None,
) -> list[dict[str, Any]]:
    market = market.upper()
    rows = _fetch_rows(market=market, date=date, dce_csv_by_date=dce_csv_by_date or {})
    snapshot_day = _date8_to_iso(date)
    accessed_at = datetime.now().astimezone().isoformat(timespec="seconds")
    grouped: dict[tuple[str, str, float], list[str]] = defaultdict(list)
    product_symbols: dict[str, set[str]] = defaultdict(set)
    labels: dict[str, str] = {}
    source_urls: dict[str, str] = {}
    for row in rows:
        product = str(row["instrument"]).upper()
        symbol = str(row["symbol"]).upper()
        product_symbols[product].add(symbol)
        labels[product] = str(row.get("instrument_label") or product)
        source_urls[product] = str(row["source_url"])
        for field, value in row["values"].items():
            if value is None:
                continue
            grouped[(product, field, float(value))].append(symbol)

    by_product_field: dict[tuple[str, str], dict[float, list[str]]] = defaultdict(dict)
    for (product, field, value), symbols in grouped.items():
        by_product_field[(product, field)][value] = sorted(set(symbols))

    events: list[dict[str, Any]] = []
    for (product, field), value_symbols_by_value in sorted(by_product_field.items()):
        base_value = _product_level_asof_value(value_symbols_by_value)
        events.append(_event(
            market=market,
            date=date,
            product=product,
            label=labels.get(product, product),
            field=field,
            value=base_value,
            symbols=[],
            scope_type="all",
            snapshot_day=snapshot_day,
            source_url=source_urls[product],
            accessed_at=accessed_at,
        ))
        for value, symbols in sorted(value_symbols_by_value.items()):
            if value == base_value:
                continue
            events.append(_event(
                market=market,
                date=date,
                product=product,
                label=labels.get(product, product),
                field=field,
                value=value,
                symbols=symbols,
                scope_type="explicit",
                snapshot_day=snapshot_day,
                source_url=source_urls[product],
                accessed_at=accessed_at,
            ))
    return events


def _fetch_rows(*, market: str, date: str, dce_csv_by_date: dict[str, Any]) -> list[dict[str, Any]]:
    if market == "DCE":
        path = dce_csv_by_date.get(date)
        if path is None:
            raise ValueError(f"DCE settlement CSV not provided for {date}; pass --dce-csv")
        return _fetch_dce_rows(date=date, path=path)
    if market in SHFE_LIKE:
        return _fetch_shfe_like_rows(market=market, date=date)
    if market == "GFEX":
        return _fetch_gfex_rows(date=date)
    if market == "CFFEX":
        return _fetch_cffex_fee_rows(date=date)
    raise ValueError(f"unsupported market: {market}")


def _dce_csv_by_date(paths: list[str]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for raw_path in paths:
        path = Path(raw_path).expanduser().resolve()
        date = _dce_csv_date(path)
        if date in result and result[date] != path:
            raise ValueError(f"multiple DCE CSV files provided for {date}: {result[date]} and {path}")
        result[date] = path
    return result


def _dce_csv_date(path: Any) -> str:
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        first = handle.readline().strip()
    match = re.search(r"(20[0-9]{6})", first)
    if not match:
        raise ValueError(f"cannot parse DCE CSV snapshot date from first line: {path}")
    return match.group(1)


def _fetch_shfe_like_rows(*, market: str, date: str) -> list[dict[str, Any]]:
    base = "www.ine.cn" if market == "INE" else "www.shfe.com.cn"
    url = f"https://{base}/data/tradedata/future/dailydata/js{date}.dat"
    response = requests.get(url, headers=HEADERS, timeout=20)
    response.raise_for_status()
    rows: list[dict[str, Any]] = []
    for item in response.json().get("o_cursor") or []:
        symbol = str(item.get("INSTRUMENTID") or "").strip().upper()
        product = _instrument(symbol)
        if not symbol or not product:
            continue
        if market == "SHFE" and product in INE_INSTRUMENTS:
            continue
        if market == "INE" and product not in INE_INSTRUMENTS:
            continue
        trade_ratio = _parse_float(item.get("TRADEFEERATIO")) or 0.0
        trade_unit = _parse_float(item.get("TRADEFEEUNIT")) or 0.0
        # SHFE/INE TTRADEFEERATIO/TTRADEFEEUNIT correspond to hedge
        # transaction fees in official fee-change attachments, not normal
        # close-today fees. ISUNITODAY is a flag in this feed, not a fee value.
        # Do not map TTRADE* or ISUNITODAY into CloseToday*.
        if trade_unit:
            open_money, open_volume = 0.0, trade_unit
        else:
            # SHFE/INE publish TRADEFEERATIO in per-mille units in this feed.
            open_money, open_volume = trade_ratio / 1000.0, 0.0
        rows.append({
            "instrument": product,
            "symbol": symbol,
            "instrument_label": str(item.get("PRODUCTNAME") or product).strip(),
            "source_url": url,
            "values": {
                "OpenRatioByMoney": open_money,
                "CloseRatioByMoney": open_money,
                "OpenRatioByVolume": open_volume,
                "CloseRatioByVolume": open_volume,
                "LongMarginRatioByMoney": _parse_float(item.get("SPECLONGMARGINRATIO")),
                "ShortMarginRatioByMoney": _parse_float(item.get("SPECSHORTMARGINRATIO")),
            },
        })
    return rows


def _fetch_gfex_rows(*, date: str) -> list[dict[str, Any]]:
    url = "http://www.gfex.com.cn/u/interfacesWebTiFutAndOptSettle/loadList"
    referer = "http://www.gfex.com.cn/gfex/rjscs/ywcs.shtml"
    session = requests.Session()
    response = session.post(
        url,
        data={"trade_date": date, "variety": ""},
        headers={**HEADERS, "Referer": referer},
        timeout=20,
    )
    if response.status_code == 567:
        session.get(referer, headers=HEADERS, timeout=20)
        response = session.post(
            url,
            data={"trade_date": date, "variety": ""},
            headers={**HEADERS, "Referer": referer},
            timeout=20,
        )
    response.raise_for_status()
    payload = response.json()
    if str(payload.get("code")) != "0":
        return []
    rows: list[dict[str, Any]] = []
    for item in payload.get("data") or []:
        symbol = str(item.get("contractId") or "").strip().upper()
        product = _instrument(symbol)
        if not symbol or not product:
            continue
        style = str(item.get("style") or "").strip()
        if style == "绝对值":
            open_money = close_money = close_today_money = 0.0
            open_volume = _parse_float(item.get("openFee")) or 0.0
            close_volume = _parse_float(item.get("offsetFee")) or 0.0
            close_today_volume = _parse_float(item.get("shortOffsetFee")) or 0.0
        elif style == "比例值":
            open_money = (_parse_float(item.get("openFee")) or 0.0) / 10000.0
            close_money = (_parse_float(item.get("offsetFee")) or 0.0) / 10000.0
            close_today_money = (_parse_float(item.get("shortOffsetFee")) or 0.0) / 10000.0
            open_volume = close_volume = close_today_volume = 0.0
        else:
            continue
        rows.append({
            "instrument": product,
            "symbol": symbol,
            "instrument_label": str(item.get("variety") or product).strip(),
            "source_url": url,
            "values": {
                "OpenRatioByMoney": open_money,
                "CloseRatioByMoney": close_money,
                "CloseTodayRatioByMoney": close_today_money,
                "OpenRatioByVolume": open_volume,
                "CloseRatioByVolume": close_volume,
                "CloseTodayRatioByVolume": close_today_volume,
                "LongMarginRatioByMoney": _parse_float(item.get("specBuyRate")),
                "ShortMarginRatioByMoney": _parse_float(item.get("specSellRate")),
            },
        })
    return rows


def _fetch_dce_rows(*, date: str, path: Any) -> list[dict[str, Any]]:
    if _dce_csv_date(path) != date:
        raise ValueError(f"DCE CSV {path} does not match requested date {date}")
    source_url = f"file://{path}"
    rows: list[dict[str, Any]] = []
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        handle.readline()
        reader = csv.DictReader(handle)
        for item in reader:
            symbol = str(item.get("合约") or "").strip().upper()
            product = _instrument(symbol)
            if not symbol or not product:
                continue
            style = str(item.get("手续费收取方式") or "").strip()
            open_fee = _parse_float(item.get("手续费投机非日内开仓")) or 0.0
            close_fee = _parse_float(item.get("手续费投机非日内平仓")) or 0.0
            close_today_fee = _parse_float(item.get("手续费投机日内平仓")) or 0.0
            if style == "绝对值":
                open_money, open_volume = 0.0, open_fee
                close_money, close_volume = 0.0, close_fee
                close_today_money, close_today_volume = 0.0, close_today_fee
            elif style == "比例值":
                open_money, open_volume = open_fee / 10000.0, 0.0
                close_money, close_volume = close_fee / 10000.0, 0.0
                close_today_money, close_today_volume = close_today_fee / 10000.0, 0.0
            else:
                continue
            rows.append({
                "instrument": product,
                "symbol": symbol,
                "instrument_label": str(item.get("品种名称") or product).strip(),
                "source_url": source_url,
                "values": {
                    "OpenRatioByMoney": open_money,
                    "CloseRatioByMoney": close_money,
                    "CloseTodayRatioByMoney": close_today_money,
                    "OpenRatioByVolume": open_volume,
                    "CloseRatioByVolume": close_volume,
                    "CloseTodayRatioByVolume": close_today_volume,
                    "LongMarginRatioByMoney": _percent_value(item.get("保证金率投机买")),
                    "ShortMarginRatioByMoney": _percent_value(item.get("保证金率投机卖")),
                },
            })
    return rows


def _fetch_cffex_fee_rows(*, date: str) -> list[dict[str, Any]]:
    url = _cffex_settlement_csv_url(date)
    response = requests.get(url, headers=HEADERS, timeout=20)
    response.raise_for_status()
    text = response.content.decode("gbk", errors="replace")
    if text.lstrip().startswith("<"):
        raise ValueError(f"CFFEX settlement CSV not found for {date}: {url}")
    rows: list[dict[str, Any]] = []
    reader = csv.reader(io.StringIO(text))
    next(reader, None)
    header = next(reader, None)
    if header != ["期货合约", "合约多头保证金标准", "合约空头保证金标准", "交易手续费标准", "交割手续费标准", "平今仓收取率"]:
        raise ValueError(f"unexpected CFFEX settlement CSV header for {date}: {header}")
    for record in reader:
        if len(record) < 6:
            continue
        symbol = record[0].strip().upper()
        product = _instrument(symbol)
        if not symbol or not product:
            continue
        if product not in CFFEX_FUTURES:
            continue
        open_money, open_volume = _parse_cffex_fee(record[3])
        close_today_multiplier = _percent_value(record[5])
        close_today_money = open_money * close_today_multiplier
        close_today_volume = open_volume * close_today_multiplier
        rows.append({
            "instrument": product,
            "symbol": symbol,
            "instrument_label": product,
            "source_url": url,
            "values": {
                "OpenRatioByMoney": open_money,
                "CloseRatioByMoney": open_money,
                "CloseTodayRatioByMoney": close_today_money,
                "OpenRatioByVolume": open_volume,
                "CloseRatioByVolume": open_volume,
                "CloseTodayRatioByVolume": close_today_volume,
                "LongMarginRatioByMoney": _percent_value(record[1]),
                "ShortMarginRatioByMoney": _percent_value(record[2]),
            },
        })
    return rows


def _cffex_settlement_csv_url(date: str) -> str:
    return f"http://www.cffex.com.cn/sj/jscs/{date[:4]}{date[4:6]}/{date[6:]}/{date}_1.csv"


def _product_level_asof_value(value_symbols_by_value: dict[float, list[str]]) -> float:
    if not value_symbols_by_value:
        raise ValueError("cannot choose product-level as-of value from empty snapshot group")
    return sorted(value_symbols_by_value, key=lambda value: (-len(value_symbols_by_value[value]), value))[0]


def _event(
    *,
    market: str,
    date: str,
    product: str,
    label: str,
    field: str,
    value: float,
    symbols: list[str],
    scope_type: str,
    snapshot_day: str,
    source_url: str,
    accessed_at: str,
) -> dict[str, Any]:
    event_id = _event_id(market, date, product, field, value, [] if scope_type == "all" else symbols)
    return {
        "event_id": event_id,
        "data_source": market,
        "field_group": _field_group(field),
        "source_url": source_url,
        "source_accessed_at": accessed_at,
        "agent_name": "Codex",
        "requester_key": "side-conversation-issue-124",
        "instrument": product,
        "instrument_label": label,
        "instrument_type": "future",
        "scope_type": "product",
        "exchange": _exchange_alias(market),
        "field_name": field,
        "effective_trading_day": snapshot_day,
        "effective_timestamp": f"{snapshot_day} {'09:30:00' if market == 'CFFEX' else '09:00:00'}",
        "value": value,
        "contract_scope_type": scope_type,
        "contract_codes": [] if scope_type == "all" else symbols,
        "change_type": "asof_confirmed",
        "source_notice_id": f"{market}-settlement-parameters-{date}-asof-confirmed",
        "raw_note": (
            f"Official {market} settlement parameter snapshot({snapshot_day}). "
            "Used only as 2024-boundary as-of confirmation, not as listing baseline."
        ),
        "evidence_text": f"{market} official settlement parameter endpoint: {source_url}",
        "parser_notes": (
            "Only fields explicitly present in the official endpoint are ingested. "
            "Product-level as-of rows use the most common contract value; explicit "
            "contract rows override product-level anchors when contract values differ."
        ),
    }


def _field_group(field: str) -> str:
    if field in {"LongMarginRatioByMoney", "ShortMarginRatioByMoney"}:
        return "Margin"
    return "TransactionFee"


def _event_id(market: str, date: str, product: str, field: str, value: float, symbols: list[str]) -> str:
    safe_value = re.sub(r"[^0-9a-zA-Z]+", "_", f"{value:g}").strip("_")
    suffix = "" if not symbols else "_" + "_".join(symbols)
    return f"{market.lower()}_settlement_params_{date}_{product}_{field}_{safe_value}{suffix}".lower()


def _instrument(symbol: str) -> str:
    match = re.match(r"([A-Z]+)", str(symbol or "").strip().upper())
    return match.group(1) if match else ""


def _exchange_alias(market: str) -> str:
    return {"DCE": "DCE", "SHFE": "SHF", "INE": "INE", "GFEX": "GFE", "CFFEX": "CFE"}[market]


def _parse_float(value: Any) -> float | None:
    text = str(value or "").replace(",", "").strip()
    if not text:
        return None
    try:
        result = float(text)
    except ValueError:
        return None
    return None if math.isnan(result) else result


def _parse_cffex_fee(value: Any) -> tuple[float, float]:
    text = str(value or "").strip()
    if not text:
        return 0.0, 0.0
    if "万分之" in text:
        match = re.search(r"万分之\s*([0-9]+(?:\.[0-9]+)?)", text)
        return (float(match.group(1)) / 10000.0 if match else 0.0), 0.0
    if "元" in text:
        match = re.search(r"([0-9]+(?:\.[0-9]+)?)", text)
        return 0.0, float(match.group(1)) if match else 0.0
    return 0.0, 0.0


def _percent_value(value: Any) -> float:
    text = str(value or "").strip().replace("%", "")
    if not text:
        return 0.0
    return float(text) / 100.0


def _date8_to_iso(value: str) -> str:
    return f"{value[:4]}-{value[4:6]}-{value[6:8]}"


def _skip_existing(events: list[dict[str, Any]], *, store_key: str) -> list[dict[str, Any]]:
    if not events:
        return []
    with DataHub.get_instance().connect_store(store_key) as conn:
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

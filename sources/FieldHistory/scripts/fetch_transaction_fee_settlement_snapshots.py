"""Fetch exchange settlement-parameter fee snapshots as FieldHistory events."""

from __future__ import annotations

import argparse
import csv
import hashlib
import io
import json
import re
from pathlib import Path
from typing import Any

import requests


CFFEX_FUTURES = {"IC", "IF", "IH", "IM", "T", "TF", "TL", "TS"}
INE_INSTRUMENTS = {"SC", "LU", "NR", "BC", "EC"}
SOURCE_LABEL = {
    "SHFE": "上海期货交易所结算参数表",
    "INE": "上海国际能源交易中心结算参数表",
    "CFFEX": "中国金融期货交易所结算业务参数表",
}
HEADERS = {"User-Agent": "Mozilla/5.0"}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--date", action="append", required=True, help="Trading day, YYYYMMDD")
    parser.add_argument(
        "--market",
        action="append",
        choices=sorted(SOURCE_LABEL),
        default=[],
        help="Exchange market. Defaults to SHFE, INE, and CFFEX.",
    )
    parser.add_argument("--source-accessed-at", required=True, help="ISO timestamp for source access")
    parser.add_argument("--output", required=True, help="Output JSONL path")
    args = parser.parse_args(argv)

    markets = args.market or ["SHFE", "INE", "CFFEX"]
    rows: list[dict[str, Any]] = []
    for date in args.date:
        date = _normalize_date(date)
        for market in markets:
            if market in {"SHFE", "INE"}:
                rows.extend(_shfe_like_rows(market, date, source_accessed_at=args.source_accessed_at))
            elif market == "CFFEX":
                rows.extend(_cffex_rows(date, source_accessed_at=args.source_accessed_at))

    deduped: list[dict[str, Any]] = []
    seen: set[str] = set()
    for row in rows:
        if row["event_id"] in seen:
            continue
        seen.add(row["event_id"])
        deduped.append(row)

    output = Path(args.output).expanduser().resolve()
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(
        "".join(json.dumps(row, ensure_ascii=False, sort_keys=True) + "\n" for row in deduped),
        encoding="utf-8",
    )
    print(json.dumps({"output": str(output), "events": len(deduped)}, ensure_ascii=False, indent=2))
    return 0


def _shfe_like_rows(market: str, date: str, *, source_accessed_at: str) -> list[dict[str, Any]]:
    base = "www.ine.cn" if market == "INE" else "www.shfe.com.cn"
    url = f"https://{base}/data/tradedata/future/dailydata/js{date}.dat"
    response = requests.get(url, headers=HEADERS, timeout=30)
    response.raise_for_status()
    data = response.json().get("o_cursor", [])
    rows: list[dict[str, Any]] = []
    for item in data:
        symbol = str(item.get("INSTRUMENTID") or "")
        instrument = _instrument(symbol)
        if not symbol:
            continue
        if market == "SHFE" and instrument in INE_INSTRUMENTS:
            continue
        if market == "INE" and instrument not in INE_INSTRUMENTS:
            continue
        trade_unit = float(item.get("TRADEFEEUNIT") or 0.0)
        trade_ratio = float(item.get("TRADEFEERATIO") or 0.0)
        close_today_unit = float(item.get("TTRADEFEEUNIT") or 0.0)
        close_today_ratio = float(item.get("TTRADEFEERATIO") or 0.0)
        open_money, open_volume = (0.0, trade_unit) if trade_unit else (trade_ratio / 1000.0, 0.0)
        close_today_money, close_today_volume = (
            (0.0, close_today_unit) if close_today_unit else (close_today_ratio / 1000.0, 0.0)
        )
        label = str(item.get("PRODUCTNAME") or "")
        for leg, money, volume in (
            ("open", open_money, open_volume),
            ("close", open_money, open_volume),
            ("close_today", close_today_money, close_today_volume),
        ):
            _add_leg(
                rows,
                market=market,
                date=date,
                source_url=url,
                source_accessed_at=source_accessed_at,
                symbol=symbol,
                label=label,
                leg=leg,
                money=money,
                volume=volume,
            )
    return rows


def _cffex_rows(date: str, *, source_accessed_at: str) -> list[dict[str, Any]]:
    url = f"http://www.cffex.com.cn/sj/jscs/{date[:4]}{date[4:6]}/{date[6:]}/{date}_1.csv"
    response = requests.get(url, headers=HEADERS, timeout=30)
    if response.status_code != 200:
        return []
    text = response.content.decode("gbk", errors="ignore")
    if text.strip().startswith("<"):
        return []
    reader = csv.reader(io.StringIO(text))
    next(reader, None)
    next(reader, None)
    rows: list[dict[str, Any]] = []
    for record in reader:
        if not record or not record[0].strip():
            continue
        symbol = record[0].strip()
        instrument = _instrument(symbol)
        if instrument not in CFFEX_FUTURES:
            continue
        trade = record[3].strip() if len(record) > 3 else ""
        close_today = record[5].strip() if len(record) > 5 else ""
        open_money, open_volume = _parse_cffex_fee(trade)
        close_today_money, close_today_volume = _parse_cffex_fee(
            close_today,
            base_money=open_money,
            base_volume=open_volume,
        )
        for leg, money, volume in (
            ("open", open_money, open_volume),
            ("close", open_money, open_volume),
            ("close_today", close_today_money, close_today_volume),
        ):
            _add_leg(
                rows,
                market="CFFEX",
                date=date,
                source_url=url,
                source_accessed_at=source_accessed_at,
                symbol=symbol,
                label=instrument,
                leg=leg,
                money=money,
                volume=volume,
            )
    return rows


def _add_leg(
    rows: list[dict[str, Any]],
    *,
    market: str,
    date: str,
    source_url: str,
    source_accessed_at: str,
    symbol: str,
    label: str,
    leg: str,
    money: float,
    volume: float,
) -> None:
    fields = {
        "open": ("OpenRatioByMoney", "OpenRatioByVolume"),
        "close": ("CloseRatioByMoney", "CloseRatioByVolume"),
        "close_today": ("CloseTodayRatioByMoney", "CloseTodayRatioByVolume"),
    }[leg]
    _add_event(
        rows,
        market=market,
        date=date,
        source_url=source_url,
        source_accessed_at=source_accessed_at,
        symbol=symbol,
        label=label,
        field_name=fields[0],
        value=money,
    )
    _add_event(
        rows,
        market=market,
        date=date,
        source_url=source_url,
        source_accessed_at=source_accessed_at,
        symbol=symbol,
        label=label,
        field_name=fields[1],
        value=volume,
    )


def _add_event(
    rows: list[dict[str, Any]],
    *,
    market: str,
    date: str,
    source_url: str,
    source_accessed_at: str,
    symbol: str,
    label: str,
    field_name: str,
    value: float,
) -> None:
    instrument = _instrument(symbol)
    code = _contract_suffix(symbol)
    evidence = f"{SOURCE_LABEL[market]} {date}: {symbol} {field_name}={value}."
    rows.append({
        "agent_name": "codex",
        "contract_codes": [code] if code else [],
        "data_source": market,
        "effective_timestamp": "",
        "effective_trading_day": f"{date[:4]}-{date[4:6]}-{date[6:]}",
        "event_id": "transaction_fee_settle_" + _sha1(market, date, symbol, field_name, value),
        "evidence_text": evidence,
        "field_group": "TransactionFee",
        "field_name": field_name,
        "instrument": instrument,
        "instrument_label": label,
        "instrument_type": "future",
        "parser_notes": (
            "Official exchange settlement parameter snapshot. Both fee unit legs are written explicitly; "
            "ratio units are converted to money ratios, fixed yuan/lot units to volume fees."
        ),
        "raw_note": evidence,
        "source_accessed_at": source_accessed_at,
        "source_notice_id": f"{market}-settlement-parameters-{date}",
        "source_url": source_url,
        "value": float(value),
    })


def _parse_cffex_fee(raw: str, *, base_money: float | None = None, base_volume: float | None = None) -> tuple[float, float]:
    text = str(raw).strip()
    if not text or text.lower() == "nan":
        return 0.0, 0.0
    if "元" in text:
        match = re.search(r"([0-9]+(?:\.[0-9]+)?)", text)
        return 0.0, float(match.group(1)) if match else 0.0
    if "万分之" in text:
        match = re.search(r"万分之\s*([0-9]+(?:\.[0-9]+)?)", text)
        return (float(match.group(1)) / 10000.0 if match else 0.0), 0.0
    if text.endswith("%"):
        pct = float(text[:-1]) / 100.0
        if abs(pct) <= 1e-15:
            return 0.0, 0.0
        return (base_money or 0.0) * pct, (base_volume or 0.0) * pct
    return 0.0, 0.0


def _normalize_date(value: str) -> str:
    text = value.replace("-", "").strip()
    if not re.fullmatch(r"\d{8}", text):
        raise ValueError(f"date must be YYYYMMDD or YYYY-MM-DD: {value!r}")
    return text


def _instrument(symbol: str) -> str:
    match = re.match(r"([A-Za-z]+)", symbol.strip())
    return match.group(1).upper() if match else ""


def _contract_suffix(symbol: str) -> str:
    match = re.search(r"(\d+[A-Za-z]?)$", symbol.strip())
    return match.group(1).upper() if match else ""


def _sha1(*parts: Any) -> str:
    return hashlib.sha1("|".join(map(str, parts)).encode()).hexdigest()[:24]


if __name__ == "__main__":
    raise SystemExit(main())

"""Fetch exchange settlement-parameter fee snapshots as FieldHistory events."""

from __future__ import annotations

import argparse
import csv
import hashlib
import io
import json
import re
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import date as Date
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

import requests


CFFEX_FUTURES = {"IC", "IF", "IH", "IM", "T", "TF", "TL", "TS"}
INE_INSTRUMENTS = {"SC", "LU", "NR", "BC", "EC"}
SOURCE_LABEL = {
    "DCE": "大连商品交易所结算参数表",
    "SHFE": "上海期货交易所结算参数表",
    "INE": "上海国际能源交易中心结算参数表",
    "CFFEX": "中国金融期货交易所结算业务参数表",
    "CZCE": "郑州商品交易所期货结算参数表",
    "GFEX": "广州期货交易所期货结算参数表",
}
HEADERS = {"User-Agent": "Mozilla/5.0"}
REQUEST_TIMEOUT = 8.0


def main(argv: list[str] | None = None) -> int:
    global REQUEST_TIMEOUT

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--date", action="append", default=[], help="Trading day, YYYYMMDD")
    parser.add_argument("--start-date", default="", help="Inclusive start date for historical backfill, YYYYMMDD")
    parser.add_argument("--end-date", default="", help="Inclusive end date for historical backfill, YYYYMMDD")
    parser.add_argument(
        "--mode",
        choices=("snapshots", "changes"),
        default="snapshots",
        help="snapshots writes every official daily value; changes writes only first-seen/value-change events",
    )
    parser.add_argument("--strict", action="store_true", help="Raise on missing exchange/date instead of skipping it")
    parser.add_argument("--timeout", type=float, default=REQUEST_TIMEOUT, help="HTTP timeout seconds")
    parser.add_argument("--include-weekends", action="store_true", help="Include weekends when expanding date ranges")
    parser.add_argument("--progress-every", type=int, default=100, help="Print progress after this many exchange/date attempts")
    parser.add_argument("--workers", type=int, default=1, help="Bounded parallel HTTP workers")
    parser.add_argument(
        "--market",
        action="append",
        choices=sorted(SOURCE_LABEL),
        default=[],
        help="Exchange market. Defaults to SHFE, INE, and CFFEX.",
    )
    parser.add_argument(
        "--dce-csv",
        action="append",
        default=[],
        help=(
            "Manually downloaded DCE settlement-parameter CSV. May be repeated. "
            "Used as audit snapshot input only; DCE's site currently requires real UI interaction."
        ),
    )
    parser.add_argument("--source-accessed-at", required=True, help="ISO timestamp for source access")
    parser.add_argument("--output", required=True, help="Output JSONL path")
    args = parser.parse_args(argv)

    REQUEST_TIMEOUT = args.timeout
    markets = args.market or ["SHFE", "INE", "CFFEX", "CZCE", "GFEX"]
    dce_csv_by_date = _dce_csv_by_date(args.dce_csv)
    dates = _requested_dates(
        args.date,
        start_date=args.start_date,
        end_date=args.end_date,
        include_weekends=args.include_weekends,
    )
    if not dates:
        raise ValueError("provide --date or --start-date/--end-date")
    tasks = [(market, date) for date in dates for market in markets]
    rows = _fetch_rows(
        tasks,
        source_accessed_at=args.source_accessed_at,
        strict=args.strict,
        workers=max(1, args.workers),
        progress_every=args.progress_every,
        dce_csv_by_date=dce_csv_by_date,
    )

    deduped: list[dict[str, Any]] = []
    seen: set[str] = set()
    for row in rows:
        if row["event_id"] in seen:
            continue
        seen.add(row["event_id"])
        deduped.append(row)

    output_rows = _change_events(deduped) if args.mode == "changes" else deduped
    output = Path(args.output).expanduser().resolve()
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(
        "".join(json.dumps(row, ensure_ascii=False, sort_keys=True) + "\n" for row in output_rows),
        encoding="utf-8",
    )
    print(json.dumps({
        "output": str(output),
        "mode": args.mode,
        "snapshots": len(deduped),
        "events": len(output_rows),
    }, ensure_ascii=False, indent=2))
    return 0


def _fetch_rows(
    tasks: list[tuple[str, str]],
    *,
    source_accessed_at: str,
    strict: bool,
    workers: int,
    progress_every: int,
    dce_csv_by_date: dict[str, Path],
) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    if workers <= 1:
        for attempts, (market, date) in enumerate(tasks, start=1):
            try:
                rows.extend(
                    _rows_for_market(
                        market,
                        date,
                        source_accessed_at=source_accessed_at,
                        dce_csv_by_date=dce_csv_by_date,
                    )
                )
            except (requests.RequestException, ValueError, json.JSONDecodeError) as exc:
                if strict:
                    raise
                print(f"skip {market} {date}: {exc}", flush=True)
            if progress_every and attempts % progress_every == 0:
                print(f"progress attempts={attempts}/{len(tasks)} rows={len(rows)} latest={market}/{date}", flush=True)
        return rows

    with ThreadPoolExecutor(max_workers=workers) as executor:
        future_map = {
            executor.submit(
                _rows_for_market,
                market,
                date,
                source_accessed_at=source_accessed_at,
                dce_csv_by_date=dce_csv_by_date,
            ): (market, date)
            for market, date in tasks
        }
        for attempts, future in enumerate(as_completed(future_map), start=1):
            market, date = future_map[future]
            try:
                rows.extend(future.result())
            except (requests.RequestException, ValueError, json.JSONDecodeError) as exc:
                if strict:
                    raise
                print(f"skip {market} {date}: {exc}", flush=True)
            if progress_every and attempts % progress_every == 0:
                print(f"progress attempts={attempts}/{len(tasks)} rows={len(rows)} latest={market}/{date}", flush=True)
    return rows


def _rows_for_market(
    market: str,
    date: str,
    *,
    source_accessed_at: str,
    dce_csv_by_date: dict[str, Path],
) -> list[dict[str, Any]]:
    if market == "DCE":
        path = dce_csv_by_date.get(date)
        if path is None:
            raise ValueError(f"DCE settlement CSV not provided for {date}; pass --dce-csv")
        return _dce_rows(date, path=path, source_accessed_at=source_accessed_at)
    if market in {"SHFE", "INE"}:
        return _shfe_like_rows(market, date, source_accessed_at=source_accessed_at)
    if market == "CFFEX":
        return _cffex_rows(date, source_accessed_at=source_accessed_at)
    if market == "CZCE":
        return _czce_rows(date, source_accessed_at=source_accessed_at)
    if market == "GFEX":
        return _gfex_rows(date, source_accessed_at=source_accessed_at)
    raise ValueError(f"unsupported market: {market}")


def _dce_csv_by_date(paths: list[str]) -> dict[str, Path]:
    result: dict[str, Path] = {}
    for raw_path in paths:
        path = Path(raw_path).expanduser().resolve()
        date = _dce_csv_date(path)
        if date in result and result[date] != path:
            raise ValueError(f"multiple DCE CSV files provided for {date}: {result[date]} and {path}")
        result[date] = path
    return result


def _dce_csv_date(path: Path) -> str:
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        first = handle.readline().strip()
    match = re.search(r"(20[0-9]{6})", first)
    if not match:
        raise ValueError(f"cannot parse DCE CSV snapshot date from first line: {path}")
    return match.group(1)


def _requested_dates(
    dates: list[str],
    *,
    start_date: str = "",
    end_date: str = "",
    include_weekends: bool = False,
) -> list[str]:
    requested = {_normalize_date(value) for value in dates}
    if start_date or end_date:
        if not start_date or not end_date:
            raise ValueError("--start-date and --end-date must be provided together")
        start = _date_from_yyyymmdd(_normalize_date(start_date))
        end = _date_from_yyyymmdd(_normalize_date(end_date))
        if end < start:
            raise ValueError("--end-date must be >= --start-date")
        current = start
        while current <= end:
            if include_weekends or current.weekday() < 5:
                requested.add(current.strftime("%Y%m%d"))
            current += timedelta(days=1)
    return sorted(requested)


def _change_events(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Compress daily settlement snapshots into first-seen/value-change events."""
    sorted_rows = sorted(
        rows,
        key=lambda row: (
            str(row.get("data_source") or ""),
            str(row.get("instrument") or ""),
            json.dumps(row.get("contract_codes") or [], ensure_ascii=False),
            str(row.get("field_name") or ""),
            str(row.get("effective_trading_day") or ""),
            str(row.get("effective_timestamp") or ""),
        ),
    )
    output: list[dict[str, Any]] = []
    previous: dict[tuple[str, str, str, str], float] = {}
    for row in sorted_rows:
        key = (
            str(row.get("data_source") or ""),
            str(row.get("instrument") or ""),
            json.dumps(row.get("contract_codes") or [], ensure_ascii=False),
            str(row.get("field_name") or ""),
        )
        value = float(row.get("value") or 0.0)
        if key not in previous or abs(previous[key] - value) > 1e-15:
            output.append(row)
            previous[key] = value
    return sorted(output, key=lambda row: (str(row.get("effective_trading_day") or ""), str(row.get("event_id") or "")))


def _shfe_like_rows(market: str, date: str, *, source_accessed_at: str) -> list[dict[str, Any]]:
    base = "www.ine.cn" if market == "INE" else "www.shfe.com.cn"
    url = f"https://{base}/data/tradedata/future/dailydata/js{date}.dat"
    response = requests.get(url, headers=HEADERS, timeout=REQUEST_TIMEOUT)
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
        open_money, open_volume = (0.0, trade_unit) if trade_unit else (trade_ratio / 1000.0, 0.0)
        # SHFE/INE TTRADEFEERATIO/TTRADEFEEUNIT match hedge transaction-fee
        # values from official fee-change attachments, not normal close-today
        # values. ISUNITODAY is a feed flag, not a fee amount. Close-today rows
        # must come from explicit close-today notices or fields.
        label = str(item.get("PRODUCTNAME") or "")
        for leg, money, volume in (
            ("open", open_money, open_volume),
            ("close", open_money, open_volume),
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
    response = requests.get(url, headers=HEADERS, timeout=REQUEST_TIMEOUT)
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


def _czce_rows(date: str, *, source_accessed_at: str) -> list[dict[str, Any]]:
    url = f"http://www.czce.com.cn/cn/DFSStaticFiles/Future/{date[:4]}/{date}/FutureDataClearParams.txt"
    response = requests.get(url, headers=HEADERS, timeout=REQUEST_TIMEOUT)
    if response.status_code != 200:
        return []
    text = response.text
    if text.lstrip().startswith("<"):
        return []
    rows: list[dict[str, Any]] = []
    for item in _parse_czce_pipe_rows(text):
        symbol = str(item.get("合约代码") or "").strip()
        if not symbol or "小计" in symbol or "合计" in symbol:
            continue
        fee_type = str(item.get("手续费收取方式") or "").strip()
        trade_fee = _parse_number(item.get("交易手续费"))
        close_today_fee = _parse_number(item.get("日内平今仓交易手续费"))
        if fee_type == "绝对值":
            open_money, open_volume = 0.0, trade_fee
            close_today_money, close_today_volume = 0.0, close_today_fee
        elif fee_type == "比例值":
            open_money, open_volume = trade_fee / 10000.0, 0.0
            close_today_money, close_today_volume = close_today_fee / 10000.0, 0.0
        else:
            continue
        for leg, money, volume in (
            ("open", open_money, open_volume),
            ("close", open_money, open_volume),
            ("close_today", close_today_money, close_today_volume),
        ):
            _add_leg(
                rows,
                market="CZCE",
                date=date,
                source_url=url,
                source_accessed_at=source_accessed_at,
                symbol=symbol,
                label=_instrument(symbol),
                leg=leg,
                money=money,
                volume=volume,
            )
    return rows


def _gfex_rows(date: str, *, source_accessed_at: str) -> list[dict[str, Any]]:
    url = "http://www.gfex.com.cn/u/interfacesWebTiFutAndOptSettle/loadList"
    referer = "http://www.gfex.com.cn/gfex/rjscs/ywcs.shtml"
    session = requests.Session()
    response = session.post(
        url,
        data={"trade_date": date, "variety": ""},
        headers={**HEADERS, "Referer": referer},
        timeout=REQUEST_TIMEOUT,
    )
    if response.status_code == 567:
        session.get(referer, headers=HEADERS, timeout=REQUEST_TIMEOUT)
        response = session.post(
            url,
            data={"trade_date": date, "variety": ""},
            headers={**HEADERS, "Referer": referer},
            timeout=REQUEST_TIMEOUT,
        )
    response.raise_for_status()
    payload = response.json()
    if str(payload.get("code")) != "0":
        return []
    rows: list[dict[str, Any]] = []
    for item in payload.get("data") or []:
        symbol = str(item.get("contractId") or "").strip()
        if not symbol:
            continue
        style = str(item.get("style") or "").strip()
        open_fee = _parse_number(item.get("openFee"))
        close_fee = _parse_number(item.get("offsetFee"))
        close_today_fee = _parse_number(item.get("shortOffsetFee"))
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
        label = str(item.get("variety") or _instrument(symbol))
        for leg, money, volume in (
            ("open", open_money, open_volume),
            ("close", close_money, close_volume),
            ("close_today", close_today_money, close_today_volume),
        ):
            _add_leg(
                rows,
                market="GFEX",
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


def _dce_rows(date: str, *, path: Path, source_accessed_at: str) -> list[dict[str, Any]]:
    if _dce_csv_date(path) != date:
        raise ValueError(f"DCE CSV {path} does not match requested date {date}")
    rows: list[dict[str, Any]] = []
    source_url = f"file://{path}"
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        title = handle.readline().strip()
        reader = csv.DictReader(handle)
        for item in reader:
            symbol = str(item.get("合约") or "").strip()
            if not symbol:
                continue
            style = str(item.get("手续费收取方式") or "").strip()
            open_fee = _parse_number(item.get("手续费投机非日内开仓"))
            close_fee = _parse_number(item.get("手续费投机非日内平仓"))
            close_today_fee = _parse_number(item.get("手续费投机日内平仓"))
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
            label = str(item.get("品种名称") or _instrument(symbol))
            for leg, money, volume in (
                ("open", open_money, open_volume),
                ("close", close_money, close_volume),
                ("close_today", close_today_money, close_today_volume),
            ):
                _add_leg(
                    rows,
                    market="DCE",
                    date=date,
                    source_url=source_url,
                    source_accessed_at=source_accessed_at,
                    symbol=symbol,
                    label=label,
                    leg=leg,
                    money=money,
                    volume=volume,
                )
            rows[-1]["parser_notes"] += f" Source CSV title: {title}."
    return rows


def _parse_czce_pipe_rows(text: str) -> list[dict[str, str]]:
    lines = [line.strip("\ufeff\r\n") for line in text.splitlines() if line.strip()]
    if len(lines) < 3:
        return []
    header_idx = next((idx for idx, line in enumerate(lines) if "合约代码|" in line), -1)
    if header_idx < 0:
        return []
    columns = [col.strip() for col in lines[header_idx].split("|")]
    rows: list[dict[str, str]] = []
    for line in lines[header_idx + 1:]:
        parts = [part.strip() for part in line.split("|")]
        if len(parts) < len(columns):
            continue
        rows.append(dict(zip(columns, parts[:len(columns)])))
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
    code = _contract_suffix_for_market(symbol, market, date)
    evidence = f"{SOURCE_LABEL[market]} {date}: {symbol} {field_name}={value}."
    rows.append({
        "agent_name": "codex",
        "contract_codes": [code] if code else [],
        "data_source": market,
        "effective_timestamp": _snapshot_effective_timestamp(market, date),
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


def _snapshot_effective_timestamp(market: str, date: str) -> str:
    open_time = "09:30:00" if market == "CFFEX" else "09:00:00"
    return f"{date[:4]}-{date[4:6]}-{date[6:]} {open_time}"


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


def _parse_number(value: Any) -> float:
    text = str(value or "").replace(",", "").strip()
    if not text:
        return 0.0
    match = re.search(r"-?[0-9]+(?:\.[0-9]+)?", text)
    return float(match.group(0)) if match else 0.0


def _normalize_date(value: str) -> str:
    text = value.replace("-", "").strip()
    if not re.fullmatch(r"\d{8}", text):
        raise ValueError(f"date must be YYYYMMDD or YYYY-MM-DD: {value!r}")
    return text


def _date_from_yyyymmdd(value: str) -> Date:
    return datetime.strptime(value, "%Y%m%d").date()


def _instrument(symbol: str) -> str:
    match = re.match(r"([A-Za-z]+)", symbol.strip())
    return match.group(1).upper() if match else ""


def _contract_suffix(symbol: str) -> str:
    match = re.search(r"(\d+[A-Za-z]?)$", symbol.strip())
    return match.group(1).upper() if match else ""


def _contract_suffix_for_market(symbol: str, market: str, date: str) -> str:
    suffix = _contract_suffix(symbol)
    if market != "CZCE" or not re.fullmatch(r"\d{3}", suffix):
        return suffix
    # CZCE settlement files use one-digit year + two-digit month, e.g. AP610
    # is the AP contract expiring in 2026-10 when the queried trading day is in
    # 2026. Resolve within the nearest decade around the snapshot date.
    snapshot_year = int(date[:4])
    decade = snapshot_year - (snapshot_year % 10)
    candidate = decade + int(suffix[0])
    if candidate < snapshot_year - 5:
        candidate += 10
    elif candidate > snapshot_year + 5:
        candidate -= 10
    return f"{candidate % 100:02d}{suffix[1:]}"


def _sha1(*parts: Any) -> str:
    return hashlib.sha1("|".join(map(str, parts)).encode()).hexdigest()[:24]


if __name__ == "__main__":
    raise SystemExit(main())

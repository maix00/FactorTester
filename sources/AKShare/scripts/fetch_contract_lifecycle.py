"""Fetch CN futures contract lifecycle (list/last-trading/delivery dates) via AKShare.

DCE and GFEX take no date argument and are fetched in one call, but that call
only returns a recent rolling window (roughly the last year) of contracts,
not full history back to each exchange's inception — there is no known way
to get older delisted contracts out of these two endpoints. SHFE/INE/CZCE/
CFFEX expose a daily snapshot of contracts listed as of a queried trading
day, so this script polls a handful of historical dates (``--step-days``
apart) to discover contracts. A contract already on file is never re-fetched
into the store: known contract codes are tracked in memory across the whole
run and checked against ``known_contract_codes`` before each date's rows are
written, so repeat runs against the same date range do no redundant writes.

DCE additionally sits behind a WAF that rejects akshare's plain request
outright (412), even from a real headless-browser session. As a manual
escape hatch, set ``GTHT_DCE_COOKIE`` to a cookie string copied from a real
logged-in browser tab (DevTools → Network → any dce.com.cn request → Copy as
cURL, or Application → Cookies) before running this script; see
``sources/AKShare/client.py`` for details. The cookie is short-lived and this
is not a substitute for a real fix.

Usage:
    PYTHONPATH=. python sources/AKShare/scripts/fetch_contract_lifecycle.py \\
        --exchange ALL --start-date 20150101 --end-date 20260701 --step-days 30
"""
from __future__ import annotations

import argparse
import sys
import time
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parents[3]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from sources.AKShare import client
from sources.AKShare.lifecycle import (
    ALL_EXCHANGES,
    DATE_PARAM_EXCHANGES,
    ONE_SHOT_EXCHANGES,
    known_contract_codes,
    normalize_contract_info,
    upsert_contract_lifecycle,
)

_FETCHERS = {
    "SHFE": client.fetch_contract_info_shfe,
    "INE": client.fetch_contract_info_ine,
    "DCE": client.fetch_contract_info_dce,
    "CZCE": client.fetch_contract_info_czce,
    "CFFEX": client.fetch_contract_info_cffex,
    "GFEX": client.fetch_contract_info_gfex,
}


def _resolve_exchanges(requested: list[str]) -> list[str]:
    if not requested or "ALL" in requested:
        return list(ALL_EXCHANGES)
    ordered = [ex for ex in ALL_EXCHANGES if ex in requested]
    unknown = set(requested) - set(ALL_EXCHANGES) - {"ALL"}
    if unknown:
        raise ValueError(f"unknown exchange(s): {sorted(unknown)}")
    return ordered


def _candidate_dates(start_date: str, end_date: str, step_days: int) -> list[str]:
    start = pd.Timestamp(start_date)
    end = pd.Timestamp(end_date)
    dates = pd.date_range(start, end, freq=f"{step_days}D")
    if dates.empty or dates[-1] < end:
        dates = dates.append(pd.DatetimeIndex([end]))
    return [d.strftime("%Y%m%d") for d in dates]


def fetch_one_shot_exchange(
    exchange: str,
    *,
    db_path: str | None,
    dry_run: bool,
) -> dict[str, int]:
    try:
        df = _FETCHERS[exchange](db_path=db_path)
    except Exception as exc:
        print(f"  [{exchange}] fetch failed ({exc!r}), skipping")
        return {"requests": 1, "seen": 0, "new": 0, "inserted": 0, "errors": 1}
    rows = normalize_contract_info(exchange, df)
    known = known_contract_codes(exchange, db_path=db_path)
    new_rows = [row for row in rows if row["contract_code"] not in known]
    if dry_run:
        return {"requests": 1, "seen": len(rows), "new": len(new_rows), "inserted": 0, "errors": 0}
    result = upsert_contract_lifecycle(new_rows, db_path=db_path)
    return {"requests": 1, "seen": len(rows), "new": len(new_rows), "inserted": result["inserted"], "errors": 0}


def fetch_date_param_exchange(
    exchange: str,
    *,
    dates: list[str],
    sleep_seconds: float,
    max_requests: int,
    db_path: str | None,
    dry_run: bool,
) -> dict[str, int]:
    known = known_contract_codes(exchange, db_path=db_path)
    stats = {"requests": 0, "seen": 0, "new": 0, "inserted": 0, "errors": 0}
    for query_date in dates:
        if stats["requests"] >= max_requests:
            print(f"  [{exchange}] max-requests ({max_requests}) reached, stopping early")
            break
        try:
            df = _FETCHERS[exchange](query_date, db_path=db_path)
        except Exception as exc:
            stats["errors"] += 1
            print(f"  [{exchange}] {query_date}: fetch failed ({exc!r}), skipping")
            stats["requests"] += 1
            time.sleep(sleep_seconds)
            continue
        stats["requests"] += 1
        rows = normalize_contract_info(exchange, df, query_date=query_date)
        stats["seen"] += len(rows)
        new_rows = [row for row in rows if row["contract_code"] not in known]
        stats["new"] += len(new_rows)
        if new_rows and not dry_run:
            result = upsert_contract_lifecycle(new_rows, db_path=db_path)
            stats["inserted"] += result["inserted"]
        known.update(row["contract_code"] for row in new_rows)
        time.sleep(sleep_seconds)
    return stats


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument(
        "--exchange",
        action="append",
        choices=list(ALL_EXCHANGES) + ["ALL"],
        default=[],
        help="Exchange to fetch. Repeatable. ALL expands to all six exchanges.",
    )
    parser.add_argument("--start-date", default="20150101", help="YYYYMMDD; only used for date-snapshot exchanges")
    parser.add_argument("--end-date", default=pd.Timestamp.today().strftime("%Y%m%d"), help="YYYYMMDD")
    parser.add_argument("--step-days", type=int, default=30, help="Days between polled snapshots")
    parser.add_argument("--sleep", type=float, default=1.5, help="Seconds to sleep between requests")
    parser.add_argument("--max-requests", type=int, default=500, help="Safety cap on requests per exchange")
    parser.add_argument("--db-path", default=None, help="Override the SQLite cache path")
    parser.add_argument("--dry-run", action="store_true", help="Fetch and normalize but do not write to SQLite")
    args = parser.parse_args(argv)

    exchanges = _resolve_exchanges(args.exchange)
    dates = _candidate_dates(args.start_date, args.end_date, args.step_days)

    total = {"requests": 0, "seen": 0, "new": 0, "inserted": 0, "errors": 0}
    for exchange in exchanges:
        print(f"=== {exchange} ===")
        if exchange in ONE_SHOT_EXCHANGES:
            stats = fetch_one_shot_exchange(exchange, db_path=args.db_path, dry_run=args.dry_run)
        else:
            assert exchange in DATE_PARAM_EXCHANGES
            stats = fetch_date_param_exchange(
                exchange,
                dates=dates,
                sleep_seconds=args.sleep,
                max_requests=args.max_requests,
                db_path=args.db_path,
                dry_run=args.dry_run,
            )
        print(
            f"  requests={stats['requests']} seen={stats['seen']} "
            f"new={stats['new']} inserted={stats['inserted']} errors={stats['errors']}"
        )
        for key in total:
            total[key] += stats[key]

    print("=== total ===")
    print(
        f"  requests={total['requests']} seen={total['seen']} "
        f"new={total['new']} inserted={total['inserted']} errors={total['errors']}"
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())

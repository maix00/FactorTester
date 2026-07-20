"""Backfill 2024+ contract lifecycle coverage from LocalCNFutures daily bars.

This script is deliberately source-explicit:

* ``last_trading_date`` is the last local daily bar with a finite close only
  when the contract is not right-censored by the local data cutoff.  If the
  contract still appears active at the exchange's latest local date, the field
  is left empty rather than pretending the data cutoff is the last trading day.
* ``list_date`` is the first local daily bar with a finite close.  It is a
  coverage-derived first-seen date, not an exchange listing announcement.
* delivery dates are left empty unless another exchange/portal-specific
  lifecycle ingest has already populated them.

Rows are insert-once by ``(exchange, contract_code)`` unless ``--overwrite`` is
provided.  Run exchange official/portal ingests first when exact list/delivery
dates are available; then use this script to fill the historical gap from local
daily data.
"""
from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path
from typing import Any

import pandas as pd

ROOT = Path(__file__).resolve().parents[3]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from sources.ContractLifecycle.lifecycle import upsert_contract_lifecycle
from sources.LocalCNFutures import SOURCE_DATA_DIR
from sources.OpenCTP.client import normalise_instrument_code

SOURCE_FUNCTION = "local_cnfutures_dayk_coverage"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--start-date", default="2024-01-01", help="Include contracts whose last valid day is >= this date")
    parser.add_argument("--dayk-path", default=str(Path(SOURCE_DATA_DIR) / "data_dayk.parquet"))
    parser.add_argument("--db-path", default=None, help="Override SQLite cache path")
    parser.add_argument("--exchange", action="append", default=[], help="Exchange filter, repeatable")
    parser.add_argument("--overwrite", action="store_true", help="Overwrite existing lifecycle rows")
    parser.add_argument("--dry-run", action="store_true", help="Print stats without writing SQLite")
    args = parser.parse_args(argv)

    rows = lifecycle_rows_from_dayk(
        Path(args.dayk_path),
        start_date=args.start_date,
        exchanges=args.exchange,
    )
    if args.dry_run:
        result = {"inserted": 0, "skipped_existing": 0}
    else:
        result = upsert_contract_lifecycle(rows, overwrite=args.overwrite, db_path=args.db_path)
    by_exchange = pd.Series([row["exchange"] for row in rows]).value_counts().sort_index().to_dict() if rows else {}
    missing_last_trading_date = sum(1 for row in rows if row.get("last_trading_date") in (None, ""))
    right_censored = sum(1 for row in rows if '"right_censored": true' in str(row.get("raw_json") or ""))
    print(json.dumps({
        "dayk_path": str(Path(args.dayk_path).expanduser().resolve()),
        "start_date": args.start_date,
        "rows": len(rows),
        "by_exchange": by_exchange,
        "missing_last_trading_date": missing_last_trading_date,
        "right_censored": right_censored,
        "dry_run": args.dry_run,
        **result,
    }, ensure_ascii=False, indent=2, sort_keys=True))
    return 0


def lifecycle_rows_from_dayk(
    path: Path,
    *,
    start_date: str = "2024-01-01",
    exchanges: list[str] | tuple[str, ...] = (),
) -> list[dict[str, Any]]:
    dayk = pd.read_parquet(path)
    required = {"exchange_id", "instrument_id", "unique_instrument_id", "product_id", "trading_day", "close_price"}
    missing = required - set(dayk.columns)
    if missing:
        raise ValueError(f"dayk missing columns: {sorted(missing)}")
    df = dayk[list(required)].copy()
    df["trading_day"] = pd.to_datetime(df["trading_day"]).dt.normalize()
    df = df[df["close_price"].notna()]
    selected_exchanges = {str(exchange).upper() for exchange in exchanges if str(exchange).strip()}
    if selected_exchanges:
        df = df[df["exchange_id"].astype(str).str.upper().isin(selected_exchanges)]
    if df.empty:
        return []

    exchange_max_day = df.groupby("exchange_id")["trading_day"].max().to_dict()
    grouped = (
        df.groupby(["exchange_id", "product_id", "instrument_id", "unique_instrument_id"], dropna=False)["trading_day"]
        .agg(["min", "max", "count"])
        .reset_index()
    )
    start = pd.Timestamp(start_date).normalize()
    grouped = grouped[grouped["max"] >= start]
    rows: list[dict[str, Any]] = []
    now = time.time()
    for _, item in grouped.sort_values(["exchange_id", "instrument_id"]).iterrows():
        exchange = str(item["exchange_id"] or "").upper()
        product_code = str(item["product_id"] or "").upper()
        contract_code = normalise_instrument_code(str(item["instrument_id"] or ""))
        if not exchange or not product_code or not contract_code:
            continue
        first_day = pd.Timestamp(item["min"]).date().isoformat()
        local_last_day = pd.Timestamp(item["max"]).normalize()
        exchange_cutoff = pd.Timestamp(exchange_max_day.get(item["exchange_id"])).normalize()
        right_censored = _is_right_censored(contract_code, local_last_day, exchange_cutoff)
        last_day = None if right_censored else local_last_day.date().isoformat()
        raw = {
            "source": "LocalCNFutures data_dayk.parquet",
            "unique_instrument_id": item["unique_instrument_id"],
            "instrument_id": item["instrument_id"],
            "bar_count": int(item["count"]),
            "exchange_data_cutoff": exchange_cutoff.date().isoformat(),
            "local_last_valid_day": local_last_day.date().isoformat(),
            "right_censored": right_censored,
            "field_sources": {
                "list_date": "LocalCNFutures daily bars first finite close",
                "last_trading_date": (
                    "LocalCNFutures daily bars last finite close"
                    if not right_censored
                    else "not populated: local daily data is right-censored for this contract"
                ),
            },
            "notes": (
                "Coverage-derived historical lifecycle baseline. "
                "Run exchange official/portal lifecycle ingests first for exact list and delivery fields."
            ),
        }
        rows.append({
            "exchange": exchange,
            "product_code": product_code,
            "contract_code": contract_code,
            "list_date": first_day,
            "last_trading_date": last_day,
            "delivery_start_date": None,
            "delivery_notice_date": None,
            "last_delivery_date": None,
            "listing_base_price": None,
            "source_query_date": None,
            "source_function": SOURCE_FUNCTION,
            "raw_json": json.dumps(raw, ensure_ascii=False, default=str),
            "fetched_at": now,
        })
    return rows


def _is_right_censored(contract_code: str, local_last_day: pd.Timestamp, exchange_cutoff: pd.Timestamp) -> bool:
    """Return True when local coverage cannot prove the contract stopped trading."""

    if local_last_day >= exchange_cutoff:
        return True
    contract_month = _contract_month(contract_code)
    if contract_month is None:
        return False
    cutoff_month = exchange_cutoff.to_period("M")
    # A contract month after the local data cutoff is necessarily still
    # right-censored.  Same-month contracts are kept only when their last bar is
    # before the exchange cutoff; DCE/CZCE/SHFE/CFFEX contracts often stop
    # trading before month end.
    return contract_month > cutoff_month


def _contract_month(contract_code: str) -> pd.Period | None:
    import re

    match = re.match(r"^[A-Z]+([0-9]{3,4})", str(contract_code or "").upper())
    if not match:
        return None
    digits = match.group(1)
    if len(digits) == 3:
        year_digit = int(digits[0])
        # Local normalized CZCE symbols in dayk are already usually four-digit;
        # for a remaining 3-digit symbol, anchor to the 2020s because this
        # backfill is scoped to 2024+.
        year = 2020 + year_digit
        month = int(digits[1:])
    else:
        year = 2000 + int(digits[:2])
        month = int(digits[2:])
    if not 1 <= month <= 12:
        return None
    return pd.Period(year=year, month=month, freq="M")


if __name__ == "__main__":
    raise SystemExit(main())

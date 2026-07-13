"""Repair last_trading_date from LocalCNFutures daily bars for expiry-date rows.

Some SHFE/INE contract-info feeds expose ``EXPIREDATE``/``到期日`` but not a
separate last-trading-day field.  For products whose expiry date falls after
the last finite local daily bar, the local bar is the better last-trading-date
evidence while the remaining lifecycle fields still come from contract-info.

This script updates only rows where:

* the lifecycle row is 2024+ and comes from SHFE/INE contract-info style data;
* lifecycle.last_trading_date is after the local last finite daily bar;
* lifecycle.last_trading_date is not beyond the exchange local-data cutoff
  (future/right-censored rows are left alone);
* a matching LocalCNFutures dayk contract exists.
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

from scripts.data_dir import CACHE_DB_PATH
from sources.AKShare.lifecycle import CONTRACT_LIFECYCLE_TABLE, ensure_schema
from sources.LocalCNFutures import SOURCE_DATA_DIR
from sources.OpenCTP.client import normalise_instrument_code
from tools.data.sqlite.db import connect_sqlite


SOURCE_FUNCTION = "exchange_contract_info_local_dayk_last_trade"
REPAIRABLE_SOURCES = {
    "futures_contract_info_shfe",
    "futures_contract_info_ine",
    "official_contract_info_shfe",
    "official_contract_info_ine",
}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--start-date", default="2024-01-01")
    parser.add_argument("--dayk-path", default=str(Path(SOURCE_DATA_DIR) / "data_dayk.parquet"))
    parser.add_argument("--db-path", default=None)
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--sample-limit", type=int, default=20)
    args = parser.parse_args(argv)

    candidates = find_repair_candidates(
        dayk_path=Path(args.dayk_path),
        db_path=args.db_path,
        start_date=args.start_date,
    )
    result = {"updated": 0}
    if not args.dry_run and candidates:
        result = apply_repairs(candidates, db_path=args.db_path)
    print(json.dumps({
        "dayk_path": str(Path(args.dayk_path).expanduser().resolve()),
        "start_date": args.start_date,
        "candidate_count": len(candidates),
        "by_exchange": _counts(candidates, "exchange"),
        "dry_run": args.dry_run,
        "samples": candidates[: max(args.sample_limit, 0)],
        **result,
    }, ensure_ascii=False, indent=2, sort_keys=True, default=str))
    return 0


def find_repair_candidates(*, dayk_path: Path, db_path: str | None, start_date: str) -> list[dict[str, Any]]:
    local = _local_last_days(dayk_path, start_date=start_date)
    db = str(db_path or CACHE_DB_PATH)
    with connect_sqlite(db) as conn:
        ensure_schema(conn)
        lifecycle = pd.read_sql_query(
            f"""
            SELECT exchange, product_code, contract_code, list_date, last_trading_date,
                   expiry_date, delivery_start_date, delivery_notice_date, last_delivery_date,
                   listing_base_price, source_query_date, source_function, raw_json
            FROM {CONTRACT_LIFECYCLE_TABLE}
            WHERE last_trading_date >= ?
            """,
            conn,
            params=(start_date,),
        )
    if lifecycle.empty or local.empty:
        return []
    lifecycle["key"] = lifecycle["exchange"].astype(str).str.upper() + "|" + lifecycle["contract_code"].astype(str).str.upper()
    merged = lifecycle.merge(local, on="key", how="inner", suffixes=("", "_local"))
    merged["last_trading_day"] = pd.to_datetime(merged["last_trading_date"], errors="coerce").dt.normalize()
    merged["local_last_day"] = pd.to_datetime(merged["local_last_day"], errors="coerce").dt.normalize()
    merged["exchange_data_cutoff"] = pd.to_datetime(merged["exchange_data_cutoff"], errors="coerce").dt.normalize()
    mask = (
        merged["source_function"].isin(REPAIRABLE_SOURCES)
        & merged["last_trading_day"].notna()
        & merged["local_last_day"].notna()
        & merged["exchange_data_cutoff"].notna()
        & (merged["last_trading_day"] > merged["local_last_day"])
        & (merged["last_trading_day"] <= merged["exchange_data_cutoff"])
    )
    out: list[dict[str, Any]] = []
    for _, row in merged[mask].sort_values(["exchange", "contract_code"]).iterrows():
        raw = _json_object(row.get("raw_json"))
        original_last_trading_date = _date_text(row.get("last_trading_date"))
        original_expiry_date = _date_text(row.get("expiry_date")) or original_last_trading_date
        raw["_last_trading_date_repair"] = {
            "reason": "contract-info expiry date is after LocalCNFutures last finite daily bar",
            "original_source_function": row.get("source_function"),
            "original_last_trading_date": original_last_trading_date,
            "expiry_date": original_expiry_date,
            "replacement_last_trading_date": pd.Timestamp(row["local_last_day"]).date().isoformat(),
            "local_exchange_data_cutoff": pd.Timestamp(row["exchange_data_cutoff"]).date().isoformat(),
            "source": "LocalCNFutures data_dayk.parquet",
        }
        field_sources = raw.setdefault("field_sources", {})
        if isinstance(field_sources, dict):
            field_sources["last_trading_date"] = (
                "LocalCNFutures daily bars last finite close; original contract-info expiry date preserved "
                "in _last_trading_date_repair.original_last_trading_date"
            )
        out.append({
            "exchange": str(row["exchange"]).upper(),
            "contract_code": str(row["contract_code"]).upper(),
            "product_code": row.get("product_code"),
            "expiry_date": original_expiry_date,
            "original_last_trading_date": original_last_trading_date,
            "last_trading_date": pd.Timestamp(row["local_last_day"]).date().isoformat(),
            "source_function": SOURCE_FUNCTION,
            "raw_json": json.dumps(raw, ensure_ascii=False, default=str),
        })
    return out


def apply_repairs(candidates: list[dict[str, Any]], *, db_path: str | None) -> dict[str, int]:
    db = str(db_path or CACHE_DB_PATH)
    now = time.time()
    with connect_sqlite(db) as conn:
        ensure_schema(conn)
        conn.execute(
            f"""
            UPDATE {CONTRACT_LIFECYCLE_TABLE}
            SET expiry_date = last_trading_date
            WHERE source_function IN ({",".join("?" for _ in REPAIRABLE_SOURCES)})
              AND (expiry_date IS NULL OR expiry_date = '')
              AND last_trading_date IS NOT NULL
            """,
            tuple(sorted(REPAIRABLE_SOURCES)),
        )
        for item in candidates:
            conn.execute(
                f"""
                UPDATE {CONTRACT_LIFECYCLE_TABLE}
                SET last_trading_date = ?,
                    expiry_date = COALESCE(NULLIF(expiry_date, ''), ?),
                    source_function = ?,
                    raw_json = ?,
                    fetched_at = ?
                WHERE exchange = ? AND contract_code = ?
                """,
                (
                    item["last_trading_date"],
                    item["expiry_date"],
                    SOURCE_FUNCTION,
                    item["raw_json"],
                    now,
                    item["exchange"],
                    item["contract_code"],
                ),
            )
        conn.commit()
    return {"updated": len(candidates)}


def _local_last_days(dayk_path: Path, *, start_date: str) -> pd.DataFrame:
    dayk = pd.read_parquet(dayk_path)
    required = {"exchange_id", "product_id", "instrument_id", "trading_day", "close_price"}
    missing = required - set(dayk.columns)
    if missing:
        raise ValueError(f"dayk missing required columns: {sorted(missing)}")
    df = dayk[list(required)].copy()
    df["trading_day"] = pd.to_datetime(df["trading_day"]).dt.normalize()
    df = df[df["close_price"].notna()]
    grouped = (
        df.groupby(["exchange_id", "product_id", "instrument_id"], dropna=False)["trading_day"]
        .agg(["max", "count"])
        .reset_index()
    )
    grouped["contract_code"] = grouped["instrument_id"].map(normalise_instrument_code)
    grouped = grouped[(grouped["max"] >= pd.Timestamp(start_date)) & grouped["contract_code"].notna()]
    exchange_cutoff = df.groupby("exchange_id")["trading_day"].max().to_dict()
    grouped["exchange"] = grouped["exchange_id"].astype(str).str.upper()
    grouped["key"] = grouped["exchange"] + "|" + grouped["contract_code"].astype(str).str.upper()
    grouped["local_last_day"] = grouped["max"]
    grouped["exchange_data_cutoff"] = grouped["exchange_id"].map(exchange_cutoff)
    return grouped[["key", "local_last_day", "exchange_data_cutoff", "count"]].drop_duplicates("key")


def _json_object(value: Any) -> dict[str, Any]:
    if isinstance(value, dict):
        return dict(value)
    try:
        parsed = json.loads(value or "{}")
    except Exception:
        return {"_raw_json_parse_error": str(value)}
    return parsed if isinstance(parsed, dict) else {"raw": parsed}


def _date_text(value: Any) -> str | None:
    if value in (None, ""):
        return None
    parsed = pd.to_datetime(value, errors="coerce")
    if pd.isna(parsed):
        return str(value)
    return pd.Timestamp(parsed).date().isoformat()


def _counts(rows: list[dict[str, Any]], key: str) -> dict[str, int]:
    result: dict[str, int] = {}
    for row in rows:
        value = str(row.get(key))
        result[value] = result.get(value, 0) + 1
    return dict(sorted(result.items()))


if __name__ == "__main__":
    raise SystemExit(main())

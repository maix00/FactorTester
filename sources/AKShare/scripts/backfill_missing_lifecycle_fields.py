"""Backfill missing contract-lifecycle fields from exchange official data.

This script is intentionally narrow and provenance-preserving. It only rewrites
rows when an exchange official contract-info snapshot supplies the missing
field explicitly.

Currently supported:

* CFFEX ``listing_base_price``: query the official trading-parameter XML on the
  stored ``last_trading_date`` and overwrite the matching row with the official
  normalized lifecycle row.
* Tushare ``fut_basic`` (optional): when ``TUSHARE_TOKEN``/``TS_TOKEN``/
  ``TUSHARE_PRO_TOKEN`` is available, use ``last_ddate`` to fill missing
  DCE/GFEX ``last_delivery_date``. This is recorded as an external data-vendor
  source, not as exchange-official per-contract data.
* DCE/GFEX rule-derived delivery dates: derive ``last_delivery_date`` as the
  third exchange trading day after ``last_trading_date`` only when a product
  rule/listing source is present in ``agent_field_change_events`` and the local
  exchange calendar has at least three later trading days.
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import time
from pathlib import Path
from typing import Any

import pandas as pd

ROOT = Path(__file__).resolve().parents[3]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts.data_dir import CACHE_DB_PATH
from sources.AKShare import client
from sources.AKShare.lifecycle import CONTRACT_LIFECYCLE_TABLE, ensure_schema, normalize_contract_info, upsert_contract_lifecycle
from sources.LocalCNFutures import SOURCE_DATA_DIR
from sources.OpenCTP.client import normalise_instrument_code
from tools.data.sqlite.db import connect_sqlite

TUSHARE_SOURCE_FUNCTION = "tushare_fut_basic"
RULE_DERIVED_SOURCE_FUNCTION = "exchange_rule_dayk_calendar_derived"
_LIFECYCLE_COLUMNS = (
    "exchange",
    "product_code",
    "contract_code",
    "list_date",
    "last_trading_date",
    "delivery_start_date",
    "delivery_notice_date",
    "last_delivery_date",
    "listing_base_price",
    "source_query_date",
    "source_function",
    "raw_json",
    "fetched_at",
)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--db-path", default=None, help="Override SQLite cache path")
    parser.add_argument("--dry-run", action="store_true", help="Fetch and report rows without writing SQLite")
    parser.add_argument("--refresh", action="store_true", help="Refresh official response cache")
    parser.add_argument(
        "--source",
        action="append",
        choices=["cffex-official", "tushare", "all"],
        default=[],
        help="Backfill source to use. Defaults to all supported sources.",
    )
    parser.add_argument("--exchange", action="append", default=[], help="Exchange filter for Tushare source")
    parser.add_argument("--dayk-path", default=str(Path(SOURCE_DATA_DIR) / "data_dayk.parquet"))
    parser.add_argument(
        "--derive-rule-calendar",
        action="store_true",
        help="Also fill DCE/GFEX last_delivery_date from product rule source + local exchange trading calendar",
    )
    parser.add_argument("--sample-limit", type=int, default=20)
    args = parser.parse_args(argv)

    sources = set(args.source or ["all"])
    if "all" in sources:
        sources = {"cffex-official", "tushare"}

    reports: dict[str, Any] = {}
    if "cffex-official" in sources:
        reports["cffex_listing_base_price"] = backfill_cffex_listing_base_price(
            db_path=args.db_path,
            dry_run=args.dry_run,
            refresh=args.refresh,
            sample_limit=args.sample_limit,
        )
    if "tushare" in sources:
        reports["tushare_last_delivery_date"] = backfill_tushare_last_delivery_date(
            db_path=args.db_path,
            dry_run=args.dry_run,
            exchanges=args.exchange,
            sample_limit=args.sample_limit,
        )
    if args.derive_rule_calendar:
        reports["rule_calendar_last_delivery_date"] = backfill_rule_calendar_last_delivery_date(
            dayk_path=Path(args.dayk_path),
            db_path=args.db_path,
            dry_run=args.dry_run,
            exchanges=args.exchange,
            sample_limit=args.sample_limit,
        )
    report = {"dry_run": args.dry_run, "reports": reports}
    print(json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True))
    return 1 if _has_unresolved_required_source(report) else 0


def backfill_cffex_listing_base_price(
    *,
    db_path: str | None = None,
    dry_run: bool = False,
    refresh: bool = False,
    sample_limit: int = 20,
) -> dict[str, Any]:
    missing = _cffex_missing_listing_base_price(db_path=db_path)
    if missing.empty:
        return {
            "exchange": "CFFEX",
            "field": "listing_base_price",
            "missing_before": 0,
            "found": 0,
            "written": 0,
            "dry_run": dry_run,
            "missing_after_fetch": 0,
            "missing_samples": [],
            "source": "CFFEX official trading-parameter XML",
        }

    wanted = set(missing["contract_code"].astype(str))
    rows_by_contract: dict[str, dict[str, Any]] = {}
    fetch_errors: list[dict[str, str]] = []
    for query_date in sorted(set(missing["last_trading_date"].dropna().astype(str))):
        compact_date = query_date.replace("-", "")
        try:
            frame = client.fetch_contract_info_cffex(compact_date, refresh=refresh, db_path=db_path)
            rows = normalize_contract_info("CFFEX", frame, query_date=compact_date)
        except Exception as exc:
            fetch_errors.append({"query_date": compact_date, "error": f"{type(exc).__name__}: {exc}"})
            continue
        for row in rows:
            if row["contract_code"] in wanted and row.get("listing_base_price") is not None:
                rows_by_contract[row["contract_code"]] = row

    found_rows = [rows_by_contract[contract] for contract in sorted(rows_by_contract)]
    written = 0
    if found_rows and not dry_run:
        result = upsert_contract_lifecycle(found_rows, overwrite=True, db_path=db_path)
        written = int(result["inserted"])

    missing_after_fetch = sorted(wanted - set(rows_by_contract))
    return {
        "exchange": "CFFEX",
        "field": "listing_base_price",
        "missing_before": int(len(missing)),
        "found": int(len(found_rows)),
        "written": written,
        "dry_run": dry_run,
        "missing_after_fetch": int(len(missing_after_fetch)),
        "missing_samples": missing_after_fetch[:sample_limit],
        "fetch_errors": fetch_errors[:sample_limit],
        "source": "CFFEX official trading-parameter XML",
    }


def backfill_tushare_last_delivery_date(
    *,
    db_path: str | None = None,
    dry_run: bool = False,
    exchanges: list[str] | tuple[str, ...] = (),
    sample_limit: int = 20,
) -> dict[str, Any]:
    selected_exchanges = [str(exchange).upper() for exchange in exchanges if str(exchange).strip()]
    if not selected_exchanges:
        selected_exchanges = ["DCE", "GFEX"]
    missing = _missing_last_delivery_date(db_path=db_path, exchanges=selected_exchanges)
    if missing.empty:
        return {
            "source": "Tushare fut_basic",
            "source_function": TUSHARE_SOURCE_FUNCTION,
            "exchanges": selected_exchanges,
            "missing_before": 0,
            "found": 0,
            "written": 0,
            "dry_run": dry_run,
            "missing_after_fetch": 0,
            "missing_samples": [],
        }

    token = _tushare_token()
    if not token:
        return {
            "source": "Tushare fut_basic",
            "source_function": TUSHARE_SOURCE_FUNCTION,
            "exchanges": selected_exchanges,
            "missing_before": int(len(missing)),
            "found": 0,
            "written": 0,
            "dry_run": dry_run,
            "skipped": True,
            "skip_reason": "TUSHARE_TOKEN/TS_TOKEN/TUSHARE_PRO_TOKEN is not set",
            "missing_after_fetch": int(len(missing)),
            "missing_samples": missing["contract_code"].astype(str).head(sample_limit).to_list(),
        }

    try:
        import tushare as ts
    except ImportError:
        return {
            "source": "Tushare fut_basic",
            "source_function": TUSHARE_SOURCE_FUNCTION,
            "exchanges": selected_exchanges,
            "missing_before": int(len(missing)),
            "found": 0,
            "written": 0,
            "dry_run": dry_run,
            "skipped": True,
            "skip_reason": "tushare package is not installed in the active environment",
            "missing_after_fetch": int(len(missing)),
            "missing_samples": missing["contract_code"].astype(str).head(sample_limit).to_list(),
        }

    pro = ts.pro_api(token)
    wanted = set(missing["contract_code"].astype(str))
    fetched_rows: list[dict[str, Any]] = []
    fetch_errors: list[dict[str, str]] = []
    for exchange in selected_exchanges:
        try:
            frame = pro.fut_basic(
                exchange=exchange,
                fut_type="1",
                fields=(
                    "ts_code,symbol,exchange,name,fut_code,list_date,delist_date,"
                    "last_ddate,d_month,d_mode_desc,trade_time_desc"
                ),
            )
        except Exception as exc:
            fetch_errors.append({"exchange": exchange, "error": f"{type(exc).__name__}: {exc}"})
            continue
        fetched_rows.extend(_tushare_rows(frame, wanted=wanted))

    by_contract = {row["contract_code"]: row for row in fetched_rows if row.get("last_delivery_date")}
    rows_to_write = [by_contract[contract] for contract in sorted(by_contract)]
    written = 0
    if rows_to_write and not dry_run:
        result = upsert_contract_lifecycle(rows_to_write, overwrite=True, db_path=db_path)
        written = int(result["inserted"])

    missing_after_fetch = sorted(wanted - set(by_contract))
    return {
        "source": "Tushare fut_basic",
        "source_function": TUSHARE_SOURCE_FUNCTION,
        "exchanges": selected_exchanges,
        "missing_before": int(len(missing)),
        "found": int(len(rows_to_write)),
        "written": written,
        "dry_run": dry_run,
        "missing_after_fetch": int(len(missing_after_fetch)),
        "missing_samples": missing_after_fetch[:sample_limit],
        "fetch_errors": fetch_errors[:sample_limit],
    }


def backfill_rule_calendar_last_delivery_date(
    *,
    dayk_path: Path,
    db_path: str | None = None,
    dry_run: bool = False,
    exchanges: list[str] | tuple[str, ...] = (),
    sample_limit: int = 20,
) -> dict[str, Any]:
    selected_exchanges = [str(exchange).upper() for exchange in exchanges if str(exchange).strip()]
    if not selected_exchanges:
        selected_exchanges = ["DCE", "GFEX"]
    missing = _missing_last_delivery_date(db_path=db_path, exchanges=selected_exchanges)
    if missing.empty:
        return {
            "source": "exchange product rule + LocalCNFutures exchange trading calendar",
            "source_function": RULE_DERIVED_SOURCE_FUNCTION,
            "exchanges": selected_exchanges,
            "missing_before": 0,
            "derived": 0,
            "written": 0,
            "dry_run": dry_run,
            "unresolved": 0,
            "unresolved_samples": [],
        }

    rule_sources = _rule_sources_by_exchange_product(db_path=db_path)
    calendars = _exchange_calendars(dayk_path)
    rows_to_write: list[dict[str, Any]] = []
    unresolved: list[dict[str, Any]] = []
    now = time.time()
    for _, item in missing.iterrows():
        exchange = str(item["exchange"]).upper()
        product_code = str(item["product_code"]).upper()
        contract_code = str(item["contract_code"]).upper()
        rule_source = rule_sources.get((exchange, product_code))
        calendar = calendars.get(exchange)
        last_trading_date = _date_text(item.get("last_trading_date"))
        if not rule_source:
            unresolved.append({"exchange": exchange, "contract_code": contract_code, "reason": "missing product rule source"})
            continue
        if calendar is None or calendar.empty:
            unresolved.append({"exchange": exchange, "contract_code": contract_code, "reason": "missing local exchange calendar"})
            continue
        if not last_trading_date:
            unresolved.append({"exchange": exchange, "contract_code": contract_code, "reason": "missing last_trading_date"})
            continue
        derived = _third_trading_day_after(calendar, last_trading_date)
        if derived is None:
            unresolved.append({
                "exchange": exchange,
                "contract_code": contract_code,
                "reason": "local exchange calendar has fewer than 3 trading days after last_trading_date",
            })
            continue
        raw = {
            "source": "exchange product rule + LocalCNFutures exchange trading calendar",
            "field_sources": {
                "last_delivery_date": (
                    "derived as the third exchange trading day after lifecycle.last_trading_date, "
                    "using the product rule source and LocalCNFutures exchange calendar"
                ),
                "last_trading_date": f"existing lifecycle row source_function={item.get('source_function')}",
                "exchange_calendar": str(dayk_path.expanduser().resolve()),
            },
            "derivation": {
                "formula": "last_delivery_date = third exchange trading day after last_trading_date",
                "last_trading_date": last_trading_date,
                "derived_last_delivery_date": derived,
                "calendar_exchange": exchange,
            },
            "rule_source": rule_source,
            "notes": (
                "Derived lifecycle field. This is not a per-contract exchange contract-info row; "
                "it is populated only because the exact official/portal historical row is unavailable."
            ),
        }
        rows_to_write.append({
            "exchange": exchange,
            "product_code": product_code,
            "contract_code": contract_code,
            "list_date": _date_text(item.get("list_date")),
            "last_trading_date": last_trading_date,
            "delivery_start_date": None,
            "delivery_notice_date": None,
            "last_delivery_date": derived,
            "listing_base_price": None,
            "source_query_date": None,
            "source_function": RULE_DERIVED_SOURCE_FUNCTION,
            "raw_json": json.dumps(raw, ensure_ascii=False, default=str),
            "fetched_at": now,
        })

    written = 0
    if rows_to_write and not dry_run:
        result = upsert_contract_lifecycle(rows_to_write, overwrite=True, db_path=db_path)
        written = int(result["inserted"])
    return {
        "source": "exchange product rule + LocalCNFutures exchange trading calendar",
        "source_function": RULE_DERIVED_SOURCE_FUNCTION,
        "exchanges": selected_exchanges,
        "missing_before": int(len(missing)),
        "derived": int(len(rows_to_write)),
        "written": written,
        "dry_run": dry_run,
        "unresolved": int(len(unresolved)),
        "unresolved_samples": unresolved[:sample_limit],
    }


def _cffex_missing_listing_base_price(*, db_path: str | None = None) -> pd.DataFrame:
    with connect_sqlite(db_path or CACHE_DB_PATH) as conn:
        ensure_schema(conn)
        return pd.read_sql_query(
            f"""
            SELECT exchange, product_code, contract_code, list_date, last_trading_date, source_function
            FROM {CONTRACT_LIFECYCLE_TABLE}
            WHERE exchange = 'CFFEX'
              AND last_trading_date >= '2024-01-01'
              AND listing_base_price IS NULL
            ORDER BY contract_code
            """,
            conn,
        )


def _missing_last_delivery_date(*, db_path: str | None = None, exchanges: list[str]) -> pd.DataFrame:
    placeholders = ", ".join("?" for _ in exchanges)
    with connect_sqlite(db_path or CACHE_DB_PATH) as conn:
        ensure_schema(conn)
        return pd.read_sql_query(
            f"""
            SELECT exchange, product_code, contract_code, list_date, last_trading_date, source_function
            FROM {CONTRACT_LIFECYCLE_TABLE}
            WHERE exchange IN ({placeholders})
              AND last_trading_date >= '2024-01-01'
              AND last_delivery_date IS NULL
            ORDER BY exchange, contract_code
            """,
            conn,
            params=exchanges,
        )


def _tushare_rows(frame: pd.DataFrame, *, wanted: set[str]) -> list[dict[str, Any]]:
    if frame is None or frame.empty:
        return []
    rows: list[dict[str, Any]] = []
    now = time.time()
    for _, item in frame.iterrows():
        contract_code = normalise_instrument_code(item.get("symbol"))
        if not contract_code or contract_code not in wanted:
            continue
        exchange = str(item.get("exchange") or "").upper()
        product_code = str(item.get("fut_code") or "").upper() or None
        list_date = _date_text(item.get("list_date"))
        last_trading_date = _date_text(item.get("delist_date"))
        last_delivery_date = _date_text(item.get("last_ddate"))
        if not exchange or not last_delivery_date:
            continue
        raw = item.astype(object).where(pd.notna(item), None).to_dict()
        raw["field_sources"] = {
            "list_date": "Tushare fut_basic.list_date",
            "last_trading_date": "Tushare fut_basic.delist_date",
            "last_delivery_date": "Tushare fut_basic.last_ddate",
        }
        rows.append({
            "exchange": exchange,
            "product_code": product_code,
            "contract_code": contract_code,
            "list_date": list_date,
            "last_trading_date": last_trading_date,
            "delivery_start_date": None,
            "delivery_notice_date": None,
            "last_delivery_date": last_delivery_date,
            "listing_base_price": None,
            "source_query_date": None,
            "source_function": TUSHARE_SOURCE_FUNCTION,
            "raw_json": json.dumps(raw, ensure_ascii=False, default=str),
            "fetched_at": now,
        })
    return rows


def _rule_sources_by_exchange_product(*, db_path: str | None = None) -> dict[tuple[str, str], dict[str, Any]]:
    result: dict[tuple[str, str], dict[str, Any]] = {}
    with connect_sqlite(db_path or CACHE_DB_PATH) as conn:
        ensure_schema(conn)
        rows = conn.execute(
            """
            SELECT data_source, instrument, instrument_label, source_notice_id, source_url, raw_note
            FROM agent_field_change_events
            WHERE exchange IN ('DCE', 'GFEX')
              AND instrument IS NOT NULL
              AND source_url IS NOT NULL
              AND source_url != ''
            ORDER BY
              CASE
                WHEN data_source = 'CSRC-rules-db' THEN 0
                WHEN source_notice_id LIKE '%business-rule%' THEN 1
                WHEN source_notice_id LIKE '%business-rules%' THEN 1
                WHEN source_notice_id LIKE '%listing%' THEN 2
                ELSE 9
              END,
              effective_trading_day DESC
            """
        ).fetchall()
    for row in rows:
        exchange = "GFEX" if str(row["data_source"]).upper().startswith("GFEX") else None
        if str(row["data_source"]) == "CSRC-rules-db":
            exchange = "DCE"
        elif str(row["data_source"]).upper() == "DCE":
            exchange = "DCE"
        if exchange not in {"DCE", "GFEX"}:
            continue
        product_code = str(row["instrument"] or "").upper()
        if not product_code or product_code.endswith("_F"):
            continue
        key = (exchange, product_code)
        if key in result:
            continue
        result[key] = {
            "data_source": row["data_source"],
            "product_code": product_code,
            "instrument_label": row["instrument_label"],
            "source_notice_id": row["source_notice_id"],
            "source_url": row["source_url"],
            "raw_note": row["raw_note"],
        }
    return result


def _exchange_calendars(dayk_path: Path) -> dict[str, pd.DatetimeIndex]:
    dayk = pd.read_parquet(dayk_path, columns=["exchange_id", "trading_day", "close_price"])
    dayk = dayk[dayk["close_price"].notna()].copy()
    dayk["trading_day"] = pd.to_datetime(dayk["trading_day"]).dt.normalize()
    calendars: dict[str, pd.DatetimeIndex] = {}
    for exchange, group in dayk.groupby("exchange_id", dropna=False):
        calendars[str(exchange).upper()] = pd.DatetimeIndex(sorted(group["trading_day"].dropna().unique()))
    return calendars


def _third_trading_day_after(calendar: pd.DatetimeIndex, last_trading_date: str) -> str | None:
    date = pd.Timestamp(last_trading_date).normalize()
    later = calendar[calendar > date]
    if len(later) < 3:
        return None
    return later[2].date().isoformat()


def _date_text(value: Any) -> str | None:
    if value is None:
        return None
    if not isinstance(value, str) and pd.isna(value):
        return None
    text = str(value).strip()
    if not text:
        return None
    if len(text) == 8 and text.isdigit():
        return f"{text[:4]}-{text[4:6]}-{text[6:]}"
    return text


def _tushare_token() -> str | None:
    return os.environ.get("TUSHARE_TOKEN") or os.environ.get("TS_TOKEN") or os.environ.get("TUSHARE_PRO_TOKEN")


def _has_unresolved_required_source(report: dict[str, Any]) -> bool:
    for item in report.get("reports", {}).values():
        if item.get("fetch_errors"):
            return True
        if item.get("missing_after_fetch") and not item.get("skipped"):
            return True
    return False


if __name__ == "__main__":
    raise SystemExit(main())

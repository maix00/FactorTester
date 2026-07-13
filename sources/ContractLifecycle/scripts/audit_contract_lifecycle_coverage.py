"""Audit contract lifecycle table completeness against 2024+ local daily data."""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

import pandas as pd

ROOT = Path(__file__).resolve().parents[3]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from sources.ContractLifecycle.lifecycle import read_contract_lifecycle
from sources.LocalCNFutures import SOURCE_DATA_DIR
from sources.OpenCTP.client import normalise_instrument_code


REQUIRED_COLUMNS = (
    "exchange",
    "product_code",
    "contract_code",
    "list_date",
    "last_trading_date",
    "source_function",
)

NON_LAST_REQUIRED_FIELDS_BY_EXCHANGE = {
    # Futures lifecycle fields expected from exchange contract-info style data.
    "SHFE": ("list_date", "delivery_start_date", "last_delivery_date", "listing_base_price"),
    "INE": ("list_date", "delivery_start_date", "last_delivery_date", "listing_base_price"),
    "CZCE": ("list_date", "delivery_notice_date", "last_delivery_date"),
    "DCE": ("list_date", "last_delivery_date"),
    "GFEX": ("list_date", "last_delivery_date"),
    # CFFEX financial futures have no physical delivery lifecycle dates.
    "CFFEX": ("list_date", "listing_base_price"),
}

SOURCE_FIELD_POLICY: dict[str, dict[str, Any]] = {
    "official_contract_info_shfe": {
        "source": "SHFE official ContractBaseInfo daily snapshot",
        "fields": {
            "list_date": "official OPENDATE",
            "expiry_date": "official EXPIREDATE",
            "last_trading_date": "not provided by ContractBaseInfo; may be repaired from local dayk",
            "delivery_start_date": "official STARTDELIVDATE",
            "last_delivery_date": "official ENDDELIVDATE",
            "listing_base_price": "official BASISPRICE",
        },
    },
    "official_contract_info_ine": {
        "source": "INE official ContractBaseInfo daily snapshot",
        "fields": {
            "list_date": "official OPENDATE",
            "expiry_date": "official EXPIREDATE",
            "last_trading_date": "not provided by ContractBaseInfo; may be repaired from local dayk",
            "delivery_start_date": "official STARTDELIVDATE",
            "last_delivery_date": "official ENDDELIVDATE",
            "listing_base_price": "official BASISPRICE",
        },
    },
    "official_contract_info_czce": {
        "source": "CZCE official FutureDataReferenceData daily XML",
        "fields": {
            "list_date": "official firstTradingDay",
            "last_trading_date": "official lastTradingDay",
            "delivery_notice_date": "official deliveryNoticeDay",
            "last_delivery_date": "official lastDeliveryDay",
        },
    },
    "official_contract_info_cffex": {
        "source": "CFFEX official trading-parameter daily XML",
        "fields": {
            "list_date": "official opendate",
            "last_trading_date": "official expiredate",
            "listing_base_price": "official basisprice",
        },
    },
    "official_dce_portal_contract_info": {
        "source": "DCE official portal 数据中心/业务参数/合约信息 via browser context",
        "fields": {
            "list_date": "official startTradeDate",
            "last_trading_date": "official endTradeDate",
            "last_delivery_date": "official endDeliveryDate",
        },
    },
    "tushare_fut_basic": {
        "source": "Tushare Pro fut_basic external contract metadata",
        "fields": {
            "list_date": "Tushare fut_basic.list_date",
            "last_trading_date": "Tushare fut_basic.delist_date",
            "last_delivery_date": "Tushare fut_basic.last_ddate",
        },
        "note": "Optional external data-vendor source; not used unless a Tushare token is configured.",
    },
    "exchange_rule_dayk_calendar_derived": {
        "source": "Exchange product rule/listing source plus LocalCNFutures exchange trading calendar",
        "fields": {
            "list_date": "carried from prior lifecycle row",
            "last_trading_date": "carried from prior lifecycle row",
            "last_delivery_date": "derived as the third exchange trading day after last_trading_date",
        },
        "note": (
            "Derived fallback for DCE/GFEX historical contracts when exact official/portal rows are unavailable. "
            "Each raw_json includes product rule source_notice_id/source_url and calendar provenance."
        ),
    },
    "exchange_contract_info_local_dayk_last_trade": {
        "source": "Exchange contract-info row plus LocalCNFutures last finite daily bar",
        "fields": {
            "expiry_date": "exchange contract-info EXPIREDATE/到期日 when available",
            "last_trading_date": "LocalCNFutures daily bars last finite close",
            "delivery_start_date": "exchange contract-info STARTDELIVDATE/开始交割日 when available",
            "last_delivery_date": "exchange contract-info ENDDELIVDATE/最后交割日 when available",
            "listing_base_price": "exchange contract-info BASISPRICE/挂牌基准价 when available",
        },
        "note": "Used when SHFE/INE contract-info exposes expiry date but no exact last-trading-day column.",
    },
    "futures_contract_info_shfe": {
        "source": "AKShare-compatible SHFE contract-info response",
        "fields": {
            "list_date": "上市日",
            "expiry_date": "到期日",
            "last_trading_date": "not provided by this feed; may be repaired from local dayk",
            "delivery_start_date": "开始交割日",
            "last_delivery_date": "最后交割日",
            "listing_base_price": "挂牌基准价",
        },
    },
    "futures_contract_info_ine": {
        "source": "AKShare-compatible INE contract-info response",
        "fields": {
            "list_date": "上市日",
            "expiry_date": "到期日",
            "last_trading_date": "not provided by this feed; may be repaired from local dayk",
            "delivery_start_date": "开始交割日",
            "last_delivery_date": "最后交割日",
            "listing_base_price": "挂牌基准价",
        },
    },
    "futures_contract_info_czce": {
        "source": "AKShare-compatible CZCE contract-info response",
        "fields": {
            "list_date": "第一交易日",
            "last_trading_date": "最后交易日",
            "delivery_notice_date": "交割通知日",
            "last_delivery_date": "最后交割日",
        },
    },
    "futures_contract_info_cffex": {
        "source": "AKShare-compatible CFFEX contract-info response",
        "fields": {
            "list_date": "上市日",
            "last_trading_date": "最后交易日",
            "listing_base_price": "挂盘基准价",
        },
    },
    "futures_contract_info_gfex": {
        "source": "AKShare-compatible GFEX contract-info response",
        "fields": {
            "list_date": "开始交易日",
            "last_trading_date": "最后交易日",
            "last_delivery_date": "最后交割日",
        },
    },
    "local_cnfutures_dayk_coverage": {
        "source": "LocalCNFutures data_dayk.parquet coverage baseline",
        "upstream_by_exchange": {
            "DCE": "Sina daily bars fetched through AKShare futures_zh_daily_sina fallback",
            "CFFEX": "CFFEX official monthly daily-data zip",
            "SHFE": "AKShare daily futures data fetch",
            "INE": "AKShare daily futures data fetch",
            "CZCE": "AKShare daily futures data fetch",
            "GFEX": "AKShare daily futures data fetch with retries",
        },
        "fields": {
            "list_date": "first local daily bar with finite close",
            "last_trading_date": "last local daily bar with finite close only when not right-censored by exchange data cutoff",
        },
    },
}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--start-date", default="2024-01-01")
    parser.add_argument("--dayk-path", default=str(Path(SOURCE_DATA_DIR) / "data_dayk.parquet"))
    parser.add_argument("--db-path", default=None)
    parser.add_argument("--exchange", action="append", default=[])
    parser.add_argument("--sample-limit", type=int, default=20)
    parser.add_argument("--strict", action="store_true", help="Exit non-zero if coverage or required fields are incomplete")
    parser.add_argument(
        "--strict-cross-check",
        action="store_true",
        help=(
            "Also exit non-zero when local dayk ends before lifecycle.last_trading_date. "
            "Local dayk bars after an official last-trading date are reported but not fatal."
        ),
    )
    parser.add_argument(
        "--strict-non-last-fields",
        action="store_true",
        help="Also exit non-zero when exchange-specific non-last lifecycle fields are missing",
    )
    parser.add_argument("--json", action="store_true", help="Emit machine-readable JSON only")
    args = parser.parse_args(argv)

    report = audit_lifecycle_coverage(
        dayk_path=Path(args.dayk_path),
        db_path=args.db_path,
        start_date=args.start_date,
        exchanges=args.exchange,
        sample_limit=args.sample_limit,
    )
    if args.json:
        print(json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True))
    else:
        _print_human_report(report)
    if args.strict and (report["missing_count"] or report["required_field_missing_count"]):
        return 1
    if args.strict_cross_check and report["last_trading_dayk_cross_check"]["local_before_lifecycle_count"]:
        return 1
    if args.strict_non_last_fields and report["non_last_required_field_audit"]["missing_count"]:
        return 1
    return 0


def audit_lifecycle_coverage(
    *,
    dayk_path: Path,
    db_path: str | None = None,
    start_date: str = "2024-01-01",
    exchanges: list[str] | tuple[str, ...] = (),
    sample_limit: int = 20,
) -> dict[str, Any]:
    expected = _expected_contracts_from_dayk(dayk_path, start_date=start_date, exchanges=exchanges)
    lifecycle = read_contract_lifecycle(db_path=db_path)
    lifecycle = lifecycle.copy()
    lifecycle["key"] = lifecycle["exchange"].astype(str).str.upper() + "|" + lifecycle["contract_code"].astype(str).str.upper()
    expected["key"] = expected["exchange"].astype(str).str.upper() + "|" + expected["contract_code"].astype(str).str.upper()

    expected_keys = set(expected["key"])
    lifecycle_covered = lifecycle[lifecycle["key"].isin(expected_keys)].copy()
    missing = expected[~expected["key"].isin(set(lifecycle["key"]))].copy()

    required_missing = _required_field_missing(lifecycle_covered)
    by_exchange_expected = _counts(expected, "exchange")
    by_exchange_missing = _counts(missing, "exchange")
    source_distribution = _nested_counts(lifecycle_covered, ["exchange", "source_function"])
    field_completeness = _field_completeness(lifecycle_covered)
    right_censored = _right_censored_counts(lifecycle_covered)
    last_trading_cross_check = _last_trading_dayk_cross_check(lifecycle_covered, expected, sample_limit)
    non_last_required = _non_last_required_field_audit(lifecycle_covered, sample_limit)

    return {
        "dayk_path": str(dayk_path.expanduser().resolve()),
        "start_date": start_date,
        "expected_count": int(len(expected)),
        "covered_count": int(len(expected) - len(missing)),
        "missing_count": int(len(missing)),
        "coverage_ratio": (float((len(expected) - len(missing)) / len(expected)) if len(expected) else 1.0),
        "by_exchange_expected": by_exchange_expected,
        "by_exchange_missing": by_exchange_missing,
        "source_distribution": source_distribution,
        "source_field_policy": _source_field_policy_for(lifecycle_covered),
        "field_completeness": field_completeness,
        "right_censored_by_exchange": right_censored,
        "last_trading_dayk_cross_check": last_trading_cross_check,
        "non_last_required_field_audit": non_last_required,
        "required_columns": list(REQUIRED_COLUMNS),
        "required_field_missing_count": int(len(required_missing)),
        "missing_samples": _sample_records(missing, sample_limit),
        "required_field_missing_samples": _sample_records(required_missing, sample_limit),
    }


def _expected_contracts_from_dayk(
    dayk_path: Path,
    *,
    start_date: str,
    exchanges: list[str] | tuple[str, ...],
) -> pd.DataFrame:
    dayk = pd.read_parquet(dayk_path)
    required = {"exchange_id", "product_id", "instrument_id", "trading_day", "close_price"}
    missing = required - set(dayk.columns)
    if missing:
        raise ValueError(f"dayk missing required columns: {sorted(missing)}")
    df = dayk[list(required)].copy()
    df["trading_day"] = pd.to_datetime(df["trading_day"]).dt.normalize()
    df = df[df["close_price"].notna()]
    selected = {str(exchange).upper() for exchange in exchanges if str(exchange).strip()}
    if selected:
        df = df[df["exchange_id"].astype(str).str.upper().isin(selected)]
    grouped = (
        df.groupby(["exchange_id", "product_id", "instrument_id"], dropna=False)["trading_day"]
        .agg(["min", "max", "count"])
        .reset_index()
    )
    grouped["contract_code"] = grouped["instrument_id"].map(normalise_instrument_code)
    grouped = grouped[(grouped["max"] >= pd.Timestamp(start_date)) & grouped["contract_code"].notna()]
    exchange_cutoff = df.groupby("exchange_id")["trading_day"].max().to_dict()
    out = grouped.rename(columns={
        "exchange_id": "exchange",
        "product_id": "product_code",
        "min": "first_local_day",
        "max": "last_local_day",
        "count": "local_bar_count",
    })
    out["exchange_data_cutoff"] = out["exchange"].map(exchange_cutoff)
    out["right_censored_by_dayk"] = [
        _is_right_censored(str(contract), pd.Timestamp(last_day), pd.Timestamp(cutoff))
        for contract, last_day, cutoff in zip(out["contract_code"], out["last_local_day"], out["exchange_data_cutoff"], strict=False)
    ]
    return out[[
        "exchange", "product_code", "contract_code", "first_local_day", "last_local_day",
        "local_bar_count", "exchange_data_cutoff", "right_censored_by_dayk",
    ]].drop_duplicates(["exchange", "contract_code"])


def _required_field_missing(frame: pd.DataFrame) -> pd.DataFrame:
    if frame.empty:
        return frame
    checks = []
    for column in REQUIRED_COLUMNS:
        if column not in frame.columns:
            checks.append(pd.Series(True, index=frame.index))
        else:
            checks.append(frame[column].isna() | frame[column].astype(str).str.strip().isin({"", "NaN", "NaT", "nan"}))
    mask = checks[0]
    for item in checks[1:]:
        mask = mask | item
    return frame[mask]


def _field_completeness(frame: pd.DataFrame) -> dict[str, dict[str, int]]:
    fields = [
        "list_date", "expiry_date", "last_trading_date", "delivery_start_date",
        "delivery_notice_date", "last_delivery_date", "listing_base_price",
    ]
    result: dict[str, dict[str, int]] = {}
    for exchange, group in frame.groupby("exchange", dropna=False):
        result[str(exchange)] = {field: int(group[field].notna().sum()) if field in group.columns else 0 for field in fields}
        result[str(exchange)]["rows"] = int(len(group))
    return result


def _right_censored_counts(frame: pd.DataFrame) -> dict[str, int]:
    if "source_function" not in frame.columns:
        return {}
    subset = frame[frame["source_function"].eq("local_cnfutures_dayk_coverage")]
    if subset.empty:
        return {}
    # read_contract_lifecycle intentionally omits raw_json, so infer
    # right-censoring from missing last_trading_date for local coverage rows.
    censored = subset[subset["last_trading_date"].isna()]
    return _counts(censored, "exchange")


def _last_trading_dayk_cross_check(lifecycle: pd.DataFrame, expected: pd.DataFrame, sample_limit: int) -> dict[str, Any]:
    if lifecycle.empty or expected.empty:
        return {
            "compared_count": 0,
            "matched_count": 0,
            "mismatch_count": 0,
            "local_after_lifecycle_count": 0,
            "local_before_lifecycle_count": 0,
            "skipped_right_censored": 0,
            "mismatch_by_exchange": {},
            "mismatch_by_source": {},
            "mismatch_samples": [],
            "local_after_lifecycle_samples": [],
            "local_before_lifecycle_samples": [],
        }
    expected_cols = [
        "key", "first_local_day", "last_local_day", "exchange_data_cutoff", "right_censored_by_dayk",
        "local_bar_count",
    ]
    merged = lifecycle.merge(expected[expected_cols], on="key", how="left", suffixes=("", "_expected"))
    merged = merged[merged["last_trading_date"].notna()].copy()
    merged["last_trading_day"] = _parse_mixed_date_series(merged["last_trading_date"])
    merged["last_local_day"] = _parse_mixed_date_series(merged["last_local_day"])
    merged["exchange_data_cutoff"] = _parse_mixed_date_series(merged["exchange_data_cutoff"])
    merged["right_censored_by_dayk"] = merged["right_censored_by_dayk"].fillna(True)
    lifecycle_after_cutoff = merged[
        merged["last_trading_day"].notna()
        & merged["exchange_data_cutoff"].notna()
        & (merged["last_trading_day"] > merged["exchange_data_cutoff"])
    ].copy()
    comparable = merged[
        ~merged["right_censored_by_dayk"]
        & merged["last_trading_day"].notna()
        & merged["last_local_day"].notna()
        & ~merged["key"].isin(set(lifecycle_after_cutoff["key"]))
    ].copy()
    mismatches = comparable[comparable["last_trading_day"] != comparable["last_local_day"]].copy()
    local_after = comparable[comparable["last_local_day"] > comparable["last_trading_day"]].copy()
    local_before = comparable[comparable["last_local_day"] < comparable["last_trading_day"]].copy()
    return {
        "basis": (
            "Compare lifecycle.last_trading_date with LocalCNFutures last finite-close daily bar only when "
            "local dayk is not right-censored. A later local bar is reported as post-last-trading local "
            "coverage because some sources keep settlement/delivery residual rows after the official last "
            "trading date. Rows whose lifecycle last-trading date is beyond the exchange local-data cutoff "
            "are skipped as still future relative to local coverage. Strict mode only fails when local dayk "
            "ends before lifecycle.last_trading_date after these skips."
        ),
        "compared_count": int(len(comparable)),
        "matched_count": int(len(comparable) - len(mismatches)),
        "mismatch_count": int(len(mismatches)),
        "local_after_lifecycle_count": int(len(local_after)),
        "local_before_lifecycle_count": int(len(local_before)),
        "skipped_right_censored": int(merged["right_censored_by_dayk"].sum()),
        "skipped_lifecycle_after_cutoff": int(len(lifecycle_after_cutoff)),
        "mismatch_by_exchange": _counts(mismatches, "exchange"),
        "mismatch_by_source": _counts(mismatches, "source_function"),
        "mismatch_samples": _sample_records(mismatches, sample_limit),
        "local_after_lifecycle_by_exchange": _counts(local_after, "exchange"),
        "local_after_lifecycle_by_source": _counts(local_after, "source_function"),
        "local_after_lifecycle_samples": _sample_records(local_after, sample_limit),
        "local_before_lifecycle_by_exchange": _counts(local_before, "exchange"),
        "local_before_lifecycle_by_source": _counts(local_before, "source_function"),
        "local_before_lifecycle_samples": _sample_records(local_before, sample_limit),
        "lifecycle_after_cutoff_by_exchange": _counts(lifecycle_after_cutoff, "exchange"),
        "lifecycle_after_cutoff_samples": _sample_records(lifecycle_after_cutoff, sample_limit),
    }


def _non_last_required_field_audit(frame: pd.DataFrame, sample_limit: int) -> dict[str, Any]:
    if frame.empty:
        return {
            "required_fields_by_exchange": NON_LAST_REQUIRED_FIELDS_BY_EXCHANGE,
            "missing_count": 0,
            "missing_by_exchange_field": {},
            "missing_samples": [],
        }
    missing_rows: list[dict[str, Any]] = []
    for _, row in frame.iterrows():
        exchange = str(row.get("exchange") or "").upper()
        required_fields = NON_LAST_REQUIRED_FIELDS_BY_EXCHANGE.get(exchange, ())
        for field in required_fields:
            value = row.get(field)
            if _is_missing_value(value):
                missing_rows.append({
                    "exchange": exchange,
                    "product_code": row.get("product_code"),
                    "contract_code": row.get("contract_code"),
                    "source_function": row.get("source_function"),
                    "missing_field": field,
                    "list_date": row.get("list_date"),
                    "last_trading_date": row.get("last_trading_date"),
                })
    missing = pd.DataFrame(missing_rows)
    return {
        "required_fields_by_exchange": {key: list(value) for key, value in NON_LAST_REQUIRED_FIELDS_BY_EXCHANGE.items()},
        "missing_count": int(len(missing)),
        "missing_by_exchange_field": _nested_counts(missing, ["exchange", "missing_field"]) if not missing.empty else {},
        "missing_by_source": _counts(missing, "source_function") if not missing.empty else {},
        "missing_samples": _sample_records(missing, sample_limit),
    }


def _is_missing_value(value: Any) -> bool:
    if value is None:
        return True
    try:
        if pd.isna(value):
            return True
    except (TypeError, ValueError):
        pass
    return str(value).strip() in {"", "NaN", "NaT", "nan", "None"}


def _parse_mixed_date_series(values: pd.Series) -> pd.Series:
    text = values.astype("string").str.strip()
    parsed = pd.Series(pd.NaT, index=values.index, dtype="datetime64[ns]")
    compact = text.str.fullmatch(r"\d{8}").fillna(False)
    dashed = text.str.fullmatch(r"\d{4}-\d{2}-\d{2}").fillna(False)
    if compact.any():
        parsed.loc[compact] = pd.to_datetime(text.loc[compact], format="%Y%m%d", errors="coerce")
    if dashed.any():
        parsed.loc[dashed] = pd.to_datetime(text.loc[dashed], format="%Y-%m-%d", errors="coerce")
    other = ~(compact | dashed)
    if other.any():
        parsed.loc[other] = pd.to_datetime(text.loc[other], errors="coerce")
    return parsed.dt.normalize()


def _counts(frame: pd.DataFrame, column: str) -> dict[str, int]:
    if frame.empty or column not in frame.columns:
        return {}
    return {str(key): int(value) for key, value in frame.groupby(column, dropna=False).size().sort_index().items()}


def _nested_counts(frame: pd.DataFrame, columns: list[str]) -> dict[str, Any]:
    if frame.empty:
        return {}
    grouped = frame.groupby(columns, dropna=False).size()
    result: dict[str, Any] = {}
    for key, value in grouped.items():
        current = result
        parts = key if isinstance(key, tuple) else (key,)
        for part in parts[:-1]:
            current = current.setdefault(str(part), {})
        current[str(parts[-1])] = int(value)
    return result


def _is_right_censored(contract_code: str, local_last_day: pd.Timestamp, exchange_cutoff: pd.Timestamp) -> bool:
    if local_last_day >= exchange_cutoff:
        return True
    contract_month = _contract_month(contract_code)
    if contract_month is None:
        return False
    return contract_month > exchange_cutoff.to_period("M")


def _contract_month(contract_code: str) -> pd.Period | None:
    import re

    match = re.match(r"^[A-Z]+([0-9]{3,4})", str(contract_code or "").upper())
    if not match:
        return None
    digits = match.group(1)
    if len(digits) == 3:
        year = 2020 + int(digits[0])
        month = int(digits[1:])
    else:
        year = 2000 + int(digits[:2])
        month = int(digits[2:])
    if not 1 <= month <= 12:
        return None
    return pd.Period(year=year, month=month, freq="M")


def _source_field_policy_for(frame: pd.DataFrame) -> dict[str, dict[str, Any]]:
    if frame.empty or "source_function" not in frame.columns:
        return {}
    result: dict[str, dict[str, Any]] = {}
    for source_function in sorted({str(value) for value in frame["source_function"].dropna().unique()}):
        result[source_function] = SOURCE_FIELD_POLICY.get(source_function, {
            "source": f"unregistered source_function={source_function}",
            "fields": {},
        })
    return result


def _sample_records(frame: pd.DataFrame, limit: int) -> list[dict[str, Any]]:
    if frame.empty or limit <= 0:
        return []
    cols = [
        col for col in [
            "exchange", "product_code", "contract_code", "first_local_day", "last_local_day",
            "exchange_data_cutoff", "source_function", "list_date", "last_trading_date",
        ] if col in frame.columns
    ]
    sample = frame[cols].head(limit).copy()
    for col in sample.columns:
        if pd.api.types.is_datetime64_any_dtype(sample[col]):
            sample[col] = sample[col].dt.strftime("%Y-%m-%d")
    return sample.astype(object).where(sample.notna(), None).to_dict(orient="records")


def _print_human_report(report: dict[str, Any]) -> None:
    print("Contract lifecycle coverage audit")
    print(f"dayk_path: {report['dayk_path']}")
    print(f"start_date: {report['start_date']}")
    print(f"expected: {report['expected_count']}")
    print(f"covered: {report['covered_count']}")
    print(f"missing: {report['missing_count']}")
    print(f"coverage_ratio: {report['coverage_ratio']:.6f}")
    print("\nExpected by exchange:")
    print(json.dumps(report["by_exchange_expected"], ensure_ascii=False, indent=2, sort_keys=True))
    print("\nMissing by exchange:")
    print(json.dumps(report["by_exchange_missing"], ensure_ascii=False, indent=2, sort_keys=True))
    print("\nSource distribution:")
    print(json.dumps(report["source_distribution"], ensure_ascii=False, indent=2, sort_keys=True))
    print("\nSource field policy:")
    print(json.dumps(report["source_field_policy"], ensure_ascii=False, indent=2, sort_keys=True))
    print("\nField completeness:")
    print(json.dumps(report["field_completeness"], ensure_ascii=False, indent=2, sort_keys=True))
    print("\nRight-censored local coverage rows by exchange:")
    print(json.dumps(report["right_censored_by_exchange"], ensure_ascii=False, indent=2, sort_keys=True))
    print("\nLast trading date dayk cross-check:")
    print(json.dumps(report["last_trading_dayk_cross_check"], ensure_ascii=False, indent=2, sort_keys=True))
    print("\nNon-last required field audit:")
    print(json.dumps(report["non_last_required_field_audit"], ensure_ascii=False, indent=2, sort_keys=True))
    print(f"\nRequired field missing rows: {report['required_field_missing_count']}")
    if report["missing_samples"]:
        print("\nMissing samples:")
        print(json.dumps(report["missing_samples"], ensure_ascii=False, indent=2, sort_keys=True))
    if report["required_field_missing_samples"]:
        print("\nRequired field missing samples:")
        print(json.dumps(report["required_field_missing_samples"], ensure_ascii=False, indent=2, sort_keys=True))


if __name__ == "__main__":
    raise SystemExit(main())

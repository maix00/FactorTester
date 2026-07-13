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

from sources.AKShare.lifecycle import read_contract_lifecycle
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


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--start-date", default="2024-01-01")
    parser.add_argument("--dayk-path", default=str(Path(SOURCE_DATA_DIR) / "data_dayk.parquet"))
    parser.add_argument("--db-path", default=None)
    parser.add_argument("--exchange", action="append", default=[])
    parser.add_argument("--sample-limit", type=int, default=20)
    parser.add_argument("--strict", action="store_true", help="Exit non-zero if coverage or required fields are incomplete")
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
        "field_completeness": field_completeness,
        "right_censored_by_exchange": right_censored,
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
    out = grouped.rename(columns={
        "exchange_id": "exchange",
        "product_id": "product_code",
        "min": "first_local_day",
        "max": "last_local_day",
        "count": "local_bar_count",
    })
    return out[["exchange", "product_code", "contract_code", "first_local_day", "last_local_day", "local_bar_count"]].drop_duplicates(["exchange", "contract_code"])


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
    fields = ["list_date", "last_trading_date", "delivery_start_date", "delivery_notice_date", "last_delivery_date", "listing_base_price"]
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


def _sample_records(frame: pd.DataFrame, limit: int) -> list[dict[str, Any]]:
    if frame.empty or limit <= 0:
        return []
    cols = [col for col in ["exchange", "product_code", "contract_code", "first_local_day", "last_local_day", "source_function", "list_date", "last_trading_date"] if col in frame.columns]
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
    print("\nField completeness:")
    print(json.dumps(report["field_completeness"], ensure_ascii=False, indent=2, sort_keys=True))
    print("\nRight-censored local coverage rows by exchange:")
    print(json.dumps(report["right_censored_by_exchange"], ensure_ascii=False, indent=2, sort_keys=True))
    print(f"\nRequired field missing rows: {report['required_field_missing_count']}")
    if report["missing_samples"]:
        print("\nMissing samples:")
        print(json.dumps(report["missing_samples"], ensure_ascii=False, indent=2, sort_keys=True))
    if report["required_field_missing_samples"]:
        print("\nRequired field missing samples:")
        print(json.dumps(report["required_field_missing_samples"], ensure_ascii=False, indent=2, sort_keys=True))


if __name__ == "__main__":
    raise SystemExit(main())

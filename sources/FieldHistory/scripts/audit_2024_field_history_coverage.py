"""Audit all-exchange FieldHistory coverage from the 2024 boundary.

Phase 1 of the historical-field cleanup prioritises confirmed replayability
from 2024 onward.  A row may be a true listing ``baseline``, a dated ``change``,
a deterministic ``rule`` expansion, or an ``asof_confirmed`` snapshot row.  The
last one is deliberately not a baseline: it records that an exchange snapshot or
audited source confirms the state at the 2024 boundary, and can be removed later
when true older history is filled.  Products listed after the 2024 boundary must
use normal listing ``baseline`` rows and later ``change``/``rule`` rows; they
must not start from ``asof_confirmed``.
"""

from __future__ import annotations

import argparse
import csv
from collections import Counter, defaultdict
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from tools.data.field_history import _ensure_store_registered
from tools.data.hub import DataHub
from sources.FieldHistory.scripts.audit_field_history_event_chain import audit_event_chain


DEFAULT_DB = "/Users/maxdeux/Documents/GTHT/data/sqlite/unifieddata.sqlite"
DEFAULT_ASOF_DAY = "2024-01-02"

CORE_EXPECTED_FIELDS = (
    "OpenRatioByMoney",
    "CloseRatioByMoney",
    "CloseTodayRatioByMoney",
    "OpenRatioByVolume",
    "CloseRatioByVolume",
    "CloseTodayRatioByVolume",
    "LongMarginRatioByMoney",
    "ShortMarginRatioByMoney",
    "LimitUpDownRatio",
    "VolumeMultiple",
    "PriceTick",
    "MinLimitOrderVolume",
    "MaxLimitOrderVolume",
    "MaxMarketOrderVolume",
)

EXCHANGE_ALIASES = {
    "CFFEX": {"CFFEX", "CFE"},
    "CZCE": {"CZCE", "CZC"},
    "DCE": {"DCE"},
    "GFEX": {"GFEX", "GFE"},
    "INE": {"INE"},
    "SHFE": {"SHFE", "SHF"},
}

KNOWN_POST_2024_LISTING_DAYS = {
    ("DCE", "LG"): "2024-11-18",
    ("DCE", "BZ"): "2025-07-08",
    ("DCE", "L_F"): "2026-01-05",
    ("DCE", "PP_F"): "2026-01-05",
    ("DCE", "V_F"): "2026-01-05",
    ("GFEX", "PS"): "2024-12-26",
    ("GFEX", "PT"): "2025-11-27",
    ("GFEX", "PD"): "2025-11-27",
    ("SHFE", "OP"): "2025-09-10",
    ("CZCE", "PR"): "2024-08-30",
    ("CZCE", "PL"): "2025-07-22",
}

# Some upstream product catalogues expose reserve/consultation product codes
# before the exchange has actually listed tradable contracts.  They should not
# create FieldHistory coverage gaps until an official listing notice or contract
# spec exists.  Keep this list small and evidence-backed.
KNOWN_UNLISTED_PRODUCTS = {
    ("CFFEX", "IZ"),  # 深证100指数: no CFFEX fee/listing page or local contract specs as of 2026-07-09.
}


@dataclass(frozen=True, slots=True)
class Product:
    exchange: str
    instrument: str
    label: str


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--db", default=DEFAULT_DB)
    parser.add_argument("--store-key", default="")
    parser.add_argument("--asof-day", default=DEFAULT_ASOF_DAY)
    parser.add_argument("--output-csv", default="")
    parser.add_argument("--limit", type=int, default=80)
    args = parser.parse_args(argv)

    store_key = args.store_key or _store_key_for_db(args.db)
    _ensure_store_registered(DataHub.get_instance(), store_key)
    products = _load_products(store_key)
    history = _load_history(store_key)
    rows = _gap_rows(products, history, asof_day=args.asof_day)
    rows.extend(audit_event_chain(store_key=store_key, asof_day=args.asof_day))
    _print_summary(products, rows, limit=args.limit)
    if args.output_csv:
        _write_csv(Path(args.output_csv).expanduser(), rows)
        print(f"wrote 2024 coverage gaps: {Path(args.output_csv).expanduser().resolve()}")
    return 0 if not rows else 2


def _store_key_for_db(db: str) -> str:
    db_path = str(Path(db).expanduser())
    if db_path == str(Path(DEFAULT_DB).expanduser()):
        return "openctp"
    raise ValueError(f"unsupported db path for DataHub-backed audit: {db_path}")


def _load_products(store_key: str) -> list[Product]:
    with DataHub.get_instance().connect_store(store_key) as conn:
        rows = conn.execute(
            """
            SELECT ExchangeID, ProductID, ProductName
            FROM cnfutures_list
            WHERE COALESCE(ProductClass, '') = '1'
            ORDER BY ExchangeID, ProductID
            """
        ).fetchall()
    products: list[Product] = []
    for row in rows:
        exchange = str(row["ExchangeID"] or "").upper()
        instrument = str(row["ProductID"] or "").upper()
        if not exchange or not instrument:
            continue
        if (exchange, instrument) in KNOWN_UNLISTED_PRODUCTS:
            continue
        products.append(Product(exchange=exchange, instrument=instrument, label=str(row["ProductName"] or "")))
    return products


def _load_history(store_key: str) -> dict[tuple[str, str], list[dict[str, Any]]]:
    with DataHub.get_instance().connect_store(store_key) as conn:
        rows = conn.execute(
            """
            SELECT provider, source_key, instrument, instrument_label, field_name, change_type,
                   effective_trading_day, effective_timestamp, value, source_notice_id,
                   value_type, scope_type, exchange, contract_scope_type, contract_codes,
                   contract_code_start, contract_code_end
            FROM historical_field_values
            WHERE instrument_type = 'future'
            ORDER BY instrument, field_name, effective_trading_day, effective_timestamp, source_key
            """
        ).fetchall()
    history: dict[tuple[str, str], list[dict[str, Any]]] = defaultdict(list)
    for row in rows:
        record = dict(row)
        instrument = str(record.get("instrument") or "").upper()
        field = str(record.get("field_name") or "")
        if not instrument or not field:
            continue
        history[(instrument, field)].append(record)
    return history


def _gap_rows(
    products: list[Product],
    history: dict[tuple[str, str], list[dict[str, Any]]],
    *,
    asof_day: str,
) -> list[dict[str, str]]:
    rows: list[dict[str, str]] = []
    for product in products:
        product_start_day = (
            KNOWN_POST_2024_LISTING_DAYS.get((product.exchange, product.instrument))
            or _product_baseline_start_day(product, history, after_day=asof_day)
            or asof_day
        )
        required_day = max(asof_day, product_start_day)
        post_2024_listing = product_start_day > asof_day
        for field in CORE_EXPECTED_FIELDS:
            records = history.get((product.instrument, field), [])
            exchange_default_records = [
                record
                for record in history.get(("*", field), [])
                if _exchange_default_matches(record, product=product)
            ]
            all_records = records + exchange_default_records
            usable = [
                record
                for record in all_records
                if _record_applies(record, product=product, required_day=required_day)
            ]
            if not usable:
                rows.append({
                    "status": "missing_2024_state",
                    "exchange": product.exchange,
                    "instrument": product.instrument,
                    "instrument_label": product.label,
                    "field_name": field,
                    "detail": f"no baseline/change/asof_confirmed record effective on or before {required_day}",
                })
                continue
            if post_2024_listing and not any(_is_product_baseline(record, required_day=required_day) for record in records):
                rows.append({
                    "status": "missing_post_2024_listing_baseline",
                    "exchange": product.exchange,
                    "instrument": product.instrument,
                    "instrument_label": product.label,
                    "field_name": field,
                    "detail": "products listed after the 2024 boundary must start from normal baseline/change events, not asof_confirmed",
                })
                continue
            product_asof_records = [
                record for record in usable
                if _is_product_scope_asof(record)
            ]
            explicit_asof_records = [
                record for record in usable
                if _is_contract_scope_asof(record)
            ]
            if explicit_asof_records and not product_asof_records:
                rows.append({
                    "status": "missing_product_asof_anchor",
                    "exchange": product.exchange,
                    "instrument": product.instrument,
                    "instrument_label": product.label,
                    "field_name": field,
                    "detail": "contract-level asof_confirmed rows must be paired with a product-level asof_confirmed anchor",
                })
                continue
            if not any(str(record.get("change_type") or "").lower() == "asof_confirmed" for record in usable):
                # This is not a failure.  It marks rows already covered by true
                # history so snapshot backfill should not create duplicate as-of
                # rows for them.
                continue
    rows.extend(_current_snapshot_mismatch_rows(products, history, asof_day=asof_day))
    return rows


def _current_snapshot_mismatch_rows(
    products: list[Product],
    history: dict[tuple[str, str], list[dict[str, Any]]],
    *,
    asof_day: str,
) -> list[dict[str, str]]:
    rows: list[dict[str, str]] = []
    seen: set[tuple[str, str, str, str, str, str]] = set()
    for product in products:
        for field in CORE_EXPECTED_FIELDS:
            records = [
                record
                for record in history.get((product.instrument, field), []) + history.get(("*", field), [])
                if _record_belongs_to_exchange(record, product=product)
            ]
            asof_records = [
                record for record in records
                if str(record.get("change_type") or "").lower() == "asof_confirmed"
                and str(record.get("effective_trading_day") or "") > asof_day
            ]
            for snapshot in asof_records:
                prior = _latest_prior_non_asof(records, snapshot)
                if prior is None:
                    continue
                snapshot_value = _decoded_value(snapshot)
                prior_value = _decoded_value(prior)
                if _same_value(snapshot_value, prior_value):
                    continue
                key = (
                    product.exchange,
                    product.instrument,
                    field,
                    str(snapshot.get("effective_trading_day") or ""),
                    str(snapshot.get("contract_scope_type") or "all"),
                    str(snapshot.get("contract_codes") or ""),
                )
                if key in seen:
                    continue
                seen.add(key)
                rows.append({
                    "status": "current_snapshot_mismatch",
                    "exchange": product.exchange,
                    "instrument": product.instrument,
                    "instrument_label": product.label,
                    "field_name": field,
                    "detail": (
                        "current/as-of exchange snapshot value differs from latest prior "
                        "baseline/change; missing intermediate change event. "
                        f"snapshot_day={snapshot.get('effective_trading_day')} "
                        f"snapshot_value={snapshot_value!r} "
                        f"prior_day={prior.get('effective_trading_day')} "
                        f"prior_change_type={prior.get('change_type')} "
                        f"prior_value={prior_value!r} "
                        f"snapshot_notice={snapshot.get('source_notice_id') or ''} "
                        f"prior_notice={prior.get('source_notice_id') or ''}"
                    ),
                })
    return rows


def _latest_prior_non_asof(records: list[dict[str, Any]], snapshot: dict[str, Any]) -> dict[str, Any] | None:
    snapshot_day = str(snapshot.get("effective_trading_day") or "")
    snapshot_ts = str(snapshot.get("effective_timestamp") or "")
    candidates: list[dict[str, Any]] = []
    for record in records:
        if record is snapshot:
            continue
        if str(record.get("change_type") or "").lower() == "asof_confirmed":
            continue
        record_day = str(record.get("effective_trading_day") or "")
        record_ts = str(record.get("effective_timestamp") or "")
        if record_day > snapshot_day:
            continue
        if record_day == snapshot_day and snapshot_ts and record_ts and record_ts > snapshot_ts:
            continue
        if not _scope_covers(record, snapshot):
            continue
        candidates.append(record)
    if not candidates:
        return None
    return sorted(candidates, key=lambda row: (
        str(row.get("effective_trading_day") or ""),
        str(row.get("effective_timestamp") or ""),
        str(row.get("source_key") or ""),
    ))[-1]


def _scope_covers(prior: dict[str, Any], current: dict[str, Any]) -> bool:
    current_codes = _contract_codes(current)
    prior_scope = str(prior.get("contract_scope_type") or "all").lower()
    if not current_codes:
        return prior_scope == "all"
    if prior_scope == "all":
        return True
    prior_codes = set(_contract_codes(prior))
    if prior_scope == "explicit":
        return set(current_codes).issubset(prior_codes)
    start = str(prior.get("contract_code_start") or "").strip().upper()
    end = str(prior.get("contract_code_end") or "").strip().upper()
    if prior_scope == "from_contract" and start:
        return all(_compare_contract_code(code, start) >= 0 for code in current_codes)
    if prior_scope == "range" and start and end:
        return all(
            _compare_contract_code(code, start) >= 0 and _compare_contract_code(code, end) <= 0
            for code in current_codes
        )
    return False


def _contract_codes(record: dict[str, Any]) -> list[str]:
    raw = record.get("contract_codes")
    if raw is None:
        return []
    if isinstance(raw, list):
        return [str(item).strip().upper() for item in raw if str(item).strip()]
    text = str(raw).strip()
    if not text:
        return []
    try:
        import json

        parsed = json.loads(text)
    except Exception:
        parsed = None
    if isinstance(parsed, list):
        return [str(item).strip().upper() for item in parsed if str(item).strip()]
    return [item.strip().upper() for item in text.split(",") if item.strip()]


def _decoded_value(record: dict[str, Any]) -> Any:
    value = record.get("value")
    value_type = str(record.get("value_type") or "")
    if value_type == "int":
        return int(float(value))
    if value_type == "float":
        return float(value)
    if value_type == "bool":
        import json

        return json.loads(str(value))
    if value_type == "none":
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return value


def _same_value(left: Any, right: Any) -> bool:
    try:
        return abs(float(left) - float(right)) <= 1e-12
    except (TypeError, ValueError):
        return left == right


def _product_baseline_start_day(
    product: Product,
    history: dict[tuple[str, str], list[dict[str, Any]]],
    *,
    after_day: str,
) -> str | None:
    days: list[str] = []
    for field in CORE_EXPECTED_FIELDS:
        for record in history.get((product.instrument, field), []):
            if not _record_belongs_to_exchange(record, product=product):
                continue
            if not _is_product_baseline(record, required_day="9999-12-31"):
                continue
            day = str(record.get("effective_trading_day") or "")
            if day > after_day:
                days.append(day)
    return min(days) if days else None


def _record_applies(record: dict[str, Any], *, product: Product, required_day: str) -> bool:
    if not _record_belongs_to_exchange(record, product=product):
        return False
    day = str(record.get("effective_trading_day") or "")
    if day > required_day:
        return False
    change_type = str(record.get("change_type") or "").lower()
    return change_type in {"baseline", "change", "rule", "reaffirmation", "exception_unchanged", "asof_confirmed"}


def _is_product_baseline(record: dict[str, Any], *, required_day: str) -> bool:
    return (
        str(record.get("change_type") or "").lower() == "baseline"
        and str(record.get("scope_type") or "product").lower() != "exchange_default"
        and str(record.get("effective_trading_day") or "") <= required_day
    )


def _is_product_scope_asof(record: dict[str, Any]) -> bool:
    return (
        str(record.get("change_type") or "").lower() == "asof_confirmed"
        and str(record.get("scope_type") or "product").lower() != "exchange_default"
        and str(record.get("contract_scope_type") or "all").lower() == "all"
    )


def _is_contract_scope_asof(record: dict[str, Any]) -> bool:
    return (
        str(record.get("change_type") or "").lower() == "asof_confirmed"
        and str(record.get("scope_type") or "product").lower() != "exchange_default"
        and str(record.get("contract_scope_type") or "all").lower() != "all"
    )


def _record_belongs_to_exchange(record: dict[str, Any], *, product: Product) -> bool:
    if str(record.get("instrument") or "").upper() == "*":
        return _exchange_default_matches(record, product=product)
    provider = str(record.get("provider") or "")
    source_key = str(record.get("source_key") or "")
    exchange = str(record.get("exchange") or "").upper()
    aliases = EXCHANGE_ALIASES.get(product.exchange, {product.exchange})
    if provider.startswith("Agent:"):
        provider_exchange = provider.split(":", 1)[1].upper()
        if provider_exchange not in aliases and exchange not in aliases and not any(
            f"agent/{alias}/" in source_key for alias in aliases
        ):
            return False
    return True


def _exchange_default_matches(record: dict[str, Any], *, product: Product) -> bool:
    if str(record.get("instrument") or "").upper() != "*":
        return False
    if str(record.get("scope_type") or "").lower() != "exchange_default":
        return False
    exchange = str(record.get("exchange") or "").upper()
    return exchange in EXCHANGE_ALIASES.get(product.exchange, {product.exchange})


def _print_summary(products: list[Product], rows: list[dict[str, str]], *, limit: int) -> None:
    print("FieldHistory 2024+ coverage audit")
    print(f"  products: {len(products)}")
    print(f"  gap_rows: {len(rows)}")
    print("  exchange_counts:")
    for exchange, count in sorted(Counter(row["exchange"] for row in rows).items()):
        print(f"    {exchange}: {count}")
    print("  field_counts:")
    for field, count in sorted(Counter(row["field_name"] for row in rows).items()):
        print(f"    {field}: {count}")
    if rows:
        print("  samples:")
        for row in rows[: max(limit, 0)]:
            print(
                "    "
                f"{row['exchange']} {row['instrument']} {row['instrument_label']} "
                f"{row['field_name']} {row['status']}"
            )


def _write_csv(path: Path, rows: list[dict[str, str]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    columns = ["status", "exchange", "instrument", "instrument_label", "field_name", "detail"]
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=columns)
        writer.writeheader()
        writer.writerows(rows)


if __name__ == "__main__":
    raise SystemExit(main())

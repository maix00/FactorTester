"""Field-level resolver for OpenCTP online reference data.

Local price data stays in LocalCNFutures.  This module resolves reference
fields one by one, preferring values already available on local product objects
or local snapshots, then falling back to OpenCTP's online instrument endpoint.
"""
from __future__ import annotations

from functools import lru_cache
from typing import Any, Callable

import pandas as pd

from .client import fetch_instruments, _clean_instrument_rows, normalise_instrument_code


FIELD_ALIASES: dict[str, str] = {
    "point_value": "VolumeMultiple",
    "volume_multiple": "VolumeMultiple",
    "multiplier": "VolumeMultiple",
    "price_tick": "PriceTick",
    "min_tick": "PriceTick",
    "min_limit_order_volume": "MinLimitOrderVolume",
    "min_trade_quantity": "MinLimitOrderVolume",
    "max_limit_order_volume": "MaxLimitOrderVolume",
    "max_trade_quantity": "MaxLimitOrderVolume",
    "long_margin_ratio": "LongMarginRatioByMoney",
    "long_margin_fixed": "LongMarginRatioByVolume",
    "short_margin_ratio": "ShortMarginRatioByMoney",
    "short_margin_fixed": "ShortMarginRatioByVolume",
    "open_fee_ratio": "OpenRatioByMoney",
    "open_rate": "OpenRatioByMoney",
    "open_ratio": "OpenRatioByMoney",
    "open_fee_fixed": "OpenRatioByVolume",
    "open_fixed": "OpenRatioByVolume",
    "close_fee_ratio": "CloseRatioByMoney",
    "close_rate": "CloseRatioByMoney",
    "close_ratio": "CloseRatioByMoney",
    "close_fee_fixed": "CloseRatioByVolume",
    "close_fixed": "CloseRatioByVolume",
    "close_today_fee_ratio": "CloseTodayRatioByMoney",
    "close_today_rate": "CloseTodayRatioByMoney",
    "closetoday_ratio": "CloseTodayRatioByMoney",
    "close_today_fee_fixed": "CloseTodayRatioByVolume",
    "closetoday_fixed": "CloseTodayRatioByVolume",
    "close_yesterday_fee_ratio": "CloseRatioByMoney",
    "close_yesterday_rate": "CloseRatioByMoney",
    "close_yesterday_fee_fixed": "CloseRatioByVolume",
}


def canonical_field(field: str) -> str:
    key = str(field).strip()
    return FIELD_ALIASES.get(key, key)


def _contract_code(product: Any) -> str:
    name = str(getattr(product, "name", "") or getattr(product, "alias", "") or "")
    if "|" in name:
        parts = name.split("|")
        if len(parts) >= 4:
            return normalise_instrument_code(f"{parts[2]}{parts[3]}")
    return normalise_instrument_code(name.split(".")[0])


def _product_code(product: Any) -> str:
    code = str(getattr(product, "code", "") or "").strip()
    if code:
        return code
    name = str(getattr(product, "alias", getattr(product, "name", "")) or "")
    if "|" in name:
        parts = name.split("|")
        if len(parts) >= 3:
            return parts[2]
    return name.split(".")[0]


def local_product_field(product: Any, field: str) -> Any:
    """Return a field already present on a local product object, if any."""
    key = canonical_field(field)
    attrs = {
        "VolumeMultiple": ("point_value", "multiplier", "VolumeMultiple"),
        "PriceTick": ("min_tick", "price_tick", "PriceTick"),
        "MinLimitOrderVolume": ("min_trade_quantity", "lot_size", "MinLimitOrderVolume"),
    }.get(key, (key,))
    for attr in attrs:
        if hasattr(product, attr):
            value = getattr(product, attr)
            if value not in (None, ""):
                return value
    return None


def local_snapshot_field(product: Any, field: str) -> Any:
    """Return a field from LocalCNFutures local OpenCTP snapshots, if present."""
    key = canonical_field(field)
    try:
        from sources.LocalCNFutures.FeeData import get_contract_fee_row, load_latest
        from tools.products.Futures import FuturesContract
    except Exception:
        return None

    try:
        row = None
        if isinstance(product, FuturesContract):
            row = get_contract_fee_row(getattr(product, "name", ""), allow_latest_fallback=True)
        if row is None:
            df = load_latest()
            if isinstance(df, pd.DataFrame) and not df.empty and "variety_code" in df.columns:
                variety = _product_code(product).upper()
                match = df[df["variety_code"].astype(str).str.upper() == variety]
                if not match.empty:
                    row = match.iloc[0]
        if row is not None and key in row and pd.notna(row[key]):
            return row[key]
    except Exception:
        return None
    return None


@lru_cache(maxsize=2048)
def _online_contract_specs(instrument_code: str) -> pd.DataFrame:
    rows = fetch_instruments(instruments=instrument_code)
    return _clean_instrument_rows(rows)


@lru_cache(maxsize=512)
def _online_product_specs(product_code: str, markets: str | None = None) -> pd.DataFrame:
    rows = fetch_instruments(types="futures", products=product_code, markets=markets)
    return _clean_instrument_rows(rows)


def online_instrument_field(product: Any, field: str, *, markets: str | None = None) -> Any:
    """Fetch one field from OpenCTP instruments as a fallback."""
    key = canonical_field(field)
    contract = _contract_code(product)
    df = pd.DataFrame()
    if contract:
        df = _online_contract_specs(contract)
    if df.empty:
        product_code = _product_code(product)
        if product_code:
            df = _online_product_specs(product_code, markets=markets)
    if df.empty or key not in df.columns:
        return None
    value = df.iloc[0][key]
    return None if pd.isna(value) else value


def get_product_field(product: Any, field: str, *, markets: str | None = None) -> Any:
    """Resolve one reference field: local object → local snapshot → OpenCTP online."""
    return get_product_fields(product, [field], markets=markets).get(field)


def get_product_fields(
    product: Any,
    fields: list[str] | tuple[str, ...] | set[str],
    *,
    markets: str | None = None,
) -> dict[str, Any]:
    """Resolve several reference fields independently for one product."""
    ordered_fields = list(fields)
    result: dict[str, Any] = {field: None for field in ordered_fields}
    canonical_to_originals: dict[str, list[str]] = {}
    for field in ordered_fields:
        canonical = canonical_field(field)
        canonical_to_originals.setdefault(canonical, []).append(field)

    # Local product attributes first.
    for field in ordered_fields:
        value = local_product_field(product, field)
        if value not in (None, ""):
            result[field] = value

    missing_canonicals = {
        canonical for canonical, originals in canonical_to_originals.items()
        if any(result[field] in (None, "") for field in originals)
    }
    if not missing_canonicals:
        return result

    # Local snapshot next, resolved once per product.
    snapshot_values: dict[str, Any] = {}
    try:
        from sources.LocalCNFutures.FeeData import get_contract_fee_row, load_latest
        from tools.products.Futures import FuturesContract

        row = None
        if isinstance(product, FuturesContract):
            row = get_contract_fee_row(getattr(product, "name", ""), allow_latest_fallback=True)
        if row is None:
            df = load_latest()
            if isinstance(df, pd.DataFrame) and not df.empty and "variety_code" in df.columns:
                variety = _product_code(product).upper()
                match = df[df["variety_code"].astype(str).str.upper() == variety]
                if not match.empty:
                    row = match.iloc[0]
        if row is not None:
            for field in ordered_fields:
                key = canonical_field(field)
                if key in row and pd.notna(row[key]):
                    snapshot_values[field] = row[key]
                    result[field] = row[key]
    except Exception:
        snapshot_values = {}

    missing_canonicals = {
        canonical for canonical, originals in canonical_to_originals.items()
        if any(result[field] in (None, "") for field in originals)
    }
    if not missing_canonicals:
        return result

    # Online fallback is fetched once, then all missing fields are read from the same row.
    contract = _contract_code(product)
    df = pd.DataFrame()
    if contract:
        df = _online_contract_specs(contract)
    if df.empty:
        product_code = _product_code(product)
        if product_code:
            df = _online_product_specs(product_code, markets=markets)
    if not df.empty:
        row = df.iloc[0]
        for field in ordered_fields:
            if result[field] not in (None, ""):
                continue
            key = canonical_field(field)
            if key in row.index:
                value = row[key]
                if value not in (None, "") and not pd.isna(value):
                    result[field] = value

    return result


def get_products_fields(
    products: list[Any] | tuple[Any, ...],
    fields: list[str] | tuple[str, ...] | set[str],
    *,
    markets: str | None = None,
) -> list[dict[str, Any]]:
    """Resolve the same field-set for several products in one call."""
    ordered_products = list(products)
    ordered_fields = list(fields)
    return [
        get_product_fields(product, ordered_fields, markets=markets)
        for product in ordered_products
    ]


def get_products_specs_over_date_range(
    products: list[Any] | tuple[Any, ...],
    trading_days: pd.DatetimeIndex | list,
    fields: list[str] | tuple[str, ...] | set[str],
    *,
    markets: str | None = None,
) -> dict[str, pd.DataFrame]:
    """Resolve contract specs for multiple products across a date range.

    Returns a dict mapping each field name to a ``(T, P)`` DataFrame
    indexed by trading_day (rows) and variety_code (columns).
    """
    from .client import read_cnfutures_contract_specs_over_date_range

    ordered_products = list(products)
    ordered_fields = [canonical_field(f) for f in fields]

    variety_codes = [str(getattr(p, "variety_code", _product_code(p))).upper() for p in ordered_products]
    product_to_vc = {p: vc for p, vc in zip(ordered_products, variety_codes)}

    df = read_cnfutures_contract_specs_over_date_range(
        trading_days=trading_days,
        variety_codes=variety_codes,
    )

    result: dict[str, pd.DataFrame] = {}
    for field in ordered_fields:
        if field not in df.columns:
            continue
        mat = df[field].unstack(level="variety_code")
        # Reorder columns to match input product order
        existing = [vc for vc in variety_codes if vc in mat.columns]
        mat = mat.reindex(columns=existing)
        # Fill per-column (product) forward and backward
        mat = mat.ffill().bfill()
        # Cast to float64 numpy-safe
        mat = mat.astype(float)
        result[field] = mat

    return result


def make_field_getter(field: str) -> Callable[[Any], Any]:
    return lambda product: get_product_field(product, field)


get_multiplier = make_field_getter("multiplier")
get_min_tick = make_field_getter("min_tick")
get_min_trade_quantity = make_field_getter("min_trade_quantity")
get_long_margin_ratio = make_field_getter("long_margin_ratio")
get_short_margin_ratio = make_field_getter("short_margin_ratio")
get_open_ratio = make_field_getter("open_ratio")
get_open_fixed = make_field_getter("open_fixed")
get_close_ratio = make_field_getter("close_ratio")
get_close_fixed = make_field_getter("close_fixed")
get_closetoday_ratio = make_field_getter("closetoday_ratio")
get_closetoday_fixed = make_field_getter("closetoday_fixed")

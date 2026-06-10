"""Field-level resolver for OpenCTP online reference data.

Local price data stays in LocalCNFutures.  This module resolves reference
fields one by one, preferring values already available on local product objects
or local snapshots, then falling back to OpenCTP's online instrument endpoint.
"""
from __future__ import annotations

from functools import lru_cache
from typing import Any, Callable

import pandas as pd

from .client import fetch_instruments, instruments_to_contract_specs, normalise_instrument_code


FIELD_ALIASES: dict[str, str] = {
    "point_value": "multiplier",
    "volume_multiple": "multiplier",
    "price_tick": "min_tick",
    "min_limit_order_volume": "min_trade_quantity",
    "max_limit_order_volume": "max_trade_quantity",
    "open_fee_ratio": "open_ratio",
    "open_rate": "open_ratio",
    "open_fee_fixed": "open_fixed",
    "close_fee_ratio": "close_ratio",
    "close_rate": "close_ratio",
    "close_fee_fixed": "close_fixed",
    "close_today_fee_ratio": "closetoday_ratio",
    "close_today_rate": "closetoday_ratio",
    "close_today_fee_fixed": "closetoday_fixed",
    "close_yesterday_fee_ratio": "close_ratio",
    "close_yesterday_rate": "close_ratio",
    "close_yesterday_fee_fixed": "close_fixed",
}

ONLINE_FIELD_TO_LOCAL: dict[str, str] = {
    "multiplier": "VolumeMultiple",
    "min_tick": "PriceTick",
    "min_trade_quantity": "MinLimitOrderVolume",
    "max_trade_quantity": "MaxLimitOrderVolume",
    "long_margin_ratio": "LongMarginRatioByMoney",
    "long_margin_fixed": "LongMarginRatioByVolume",
    "short_margin_ratio": "ShortMarginRatioByMoney",
    "short_margin_fixed": "ShortMarginRatioByVolume",
    "open_ratio": "OpenRatioByMoney",
    "open_fixed": "OpenRatioByVolume",
    "close_ratio": "CloseRatioByMoney",
    "close_fixed": "CloseRatioByVolume",
    "closetoday_ratio": "CloseTodayRatioByMoney",
    "closetoday_fixed": "CloseTodayRatioByVolume",
    "product_class": "ProductClass",
    "open_date": "OpenDate",
    "expire_date": "ExpireDate",
    "delivery_date": "DeliveryDate",
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
        "multiplier": ("point_value", "multiplier"),
        "min_tick": ("min_tick", "price_tick"),
        "min_trade_quantity": ("min_trade_quantity", "lot_size"),
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
    return instruments_to_contract_specs(rows)


@lru_cache(maxsize=512)
def _online_product_specs(product_code: str, markets: str | None = None) -> pd.DataFrame:
    rows = fetch_instruments(types="futures", products=product_code, markets=markets)
    return instruments_to_contract_specs(rows)


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
    for getter in (
        local_product_field,
        local_snapshot_field,
        lambda p, f: online_instrument_field(p, f, markets=markets),
    ):
        value = getter(product, field)
        if value not in (None, ""):
            return value
    return None


def get_product_fields(
    product: Any,
    fields: list[str] | tuple[str, ...] | set[str],
    *,
    markets: str | None = None,
) -> dict[str, Any]:
    """Resolve several reference fields independently for one product."""
    return {
        field: get_product_field(product, field, markets=markets)
        for field in fields
    }


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

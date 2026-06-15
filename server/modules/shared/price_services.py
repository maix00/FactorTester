"""Service helpers for price viewer and price-series APIs."""

from __future__ import annotations

import os
import re
from functools import lru_cache
from typing import Any, cast

import pandas as pd

from Settings import get_all_products, get_cat_tree
from sources.LocalCNFutures import MINK_PRODUCT_DIR
from sources.LocalCNFutures.CNFutures import (
    CNFuturesContract,
    CNFuturesDayNightTimeCategory,
    CNFuturesSectorCategory,
    exchange_map,
    get_all_futures_contract,
)
from tools.products.AdjustableTermStructure import AdjustableProductMixin
from tools.products.Futures import (
    FuturesContract,
    make_contract_category_from_futures_category,
    map_contracts_to_futures,
)
from tools.products.Product import Product
from tools.products.categories.Category import CategoryTree, combine_trees


@lru_cache(maxsize=1)
def cached_products():
    return tuple(get_all_products())


@lru_cache(maxsize=1)
def cached_contracts():
    return tuple(get_all_futures_contract())


@lru_cache(maxsize=1)
def cached_product_tree() -> CategoryTree:
    return build_product_tree()


def contract_data_path(contract_uid: str) -> str:
    return os.path.join(MINK_PRODUCT_DIR, f"{contract_uid}.parquet")


def contract_has_data(contract_uid: str) -> bool:
    return os.path.isfile(contract_data_path(contract_uid))


def scalar(value: Any) -> Any:
    return value.item() if hasattr(value, 'item') else value


def timestamp_or_none(value: Any) -> pd.Timestamp | None:
    value = scalar(value)
    if pd.isna(value):
        return None
    return cast(pd.Timestamp, pd.Timestamp(value))


def build_product_tree() -> CategoryTree:
    """产品树：原品种分类 + 合约类型继承链。"""
    product_tree = get_cat_tree()
    contracts = list(cached_contracts())
    contract_tree = get_contract_category_tree(contracts)
    return combine_trees(product_tree, contract_tree)


def get_contract_category_tree(contracts) -> CategoryTree:
    """Build a CNFuturesContract tree that mirrors CNFutures category labels."""
    contract_to_future = map_contracts_to_futures_for_categories(contracts)

    sector_category = make_contract_category_from_futures_category(
        CNFuturesSectorCategory,
        CNFuturesContract,
        contracts,
        contract_to_future,
    )
    daynight_category = make_contract_category_from_futures_category(
        CNFuturesDayNightTimeCategory,
        CNFuturesContract,
        contracts,
        contract_to_future,
    )

    return (sector_category * daynight_category).get_tree_with_parents(
        all_objects=contracts,
        ancester=Product,
    )


def map_contracts_to_futures_for_categories(contracts):
    return map_contracts_to_futures(
        contracts,
        cached_products(),
        contract_key=contract_code_exchange,
        futures_key=future_code_exchange,
    )


def future_code_exchange(future):
    code = str(getattr(future, 'code', '')).upper()
    alias = str(getattr(future, 'alias', getattr(future, 'name', '')))
    exchange = alias.split('.')[1].split('@')[0].upper() if '.' in alias else ''
    return (code, exchange) if code and exchange else None


def contract_code_exchange(contract):
    name = str(getattr(contract, 'name', getattr(contract, 'alias', contract)))
    if '|' in name:
        parts = name.split('|')
        if len(parts) >= 3:
            exchange = exchange_map.get(parts[0], parts[0]).upper()
            code = parts[2].upper()
            return code, exchange

    match = re.match(r'^([A-Za-z]+)\d+\.?([A-Za-z]+)?', name)
    if match:
        code = match.group(1).upper()
        exchange = exchange_map.get(match.group(2) or '', match.group(2) or '').upper()
        return (code, exchange) if exchange else None
    return None


def available_sources_for_product(product, freq=None):
    """Serialize available data sources for one product/frequency."""
    try:
        sources = []
        freqs = [freq] if freq is not None else product.list_available_freqs()
        for data_freq in freqs:
            meta = getattr(product, data_freq.name)
            for source in meta.list_available_sources():
                sources.append({
                    'alias': source.key,
                    'freq': source.freq.name if hasattr(source.freq, 'name') else str(source.freq),
                })
        unique = {}
        for source in sources:
            unique[source['alias']] = source
        return list(unique.values())
    except Exception:
        return []


def available_freq_names_for_product(product):
    """Return frequency names that are actually provided by available data sources."""
    freqs = []
    try:
        for source in available_sources_for_product(product):
            freq = source.get('freq')
            if freq and freq not in freqs:
                freqs.append(freq)
    except Exception:
        pass
    return freqs


def find_product(products, product_name: str):
    """Find product by name or alias from an iterable."""
    return next((p for p in products if p is not None and (
        getattr(p, 'name', None) == product_name or
        getattr(p, 'alias', None) == product_name
    )), None)


def find_contract_product(contract_uid):
    contracts = cached_contracts()
    return next((contract for contract in contracts if contract is not None and (
        getattr(contract, 'name', None) == contract_uid or
        getattr(contract, 'alias', None) == contract_uid
    )), None)


def _contract_variety_code(product: Any) -> str:
    name = str(getattr(product, 'name', getattr(product, 'alias', product)))
    if '|' in name:
        parts = name.split('|')
        if len(parts) >= 3:
            return parts[2].upper()
    match = re.match(r'^([A-Za-z]+)', name)
    return match.group(1).upper() if match else ''


def _future_variety_code(product: Any) -> str:
    code = str(getattr(product, 'code', '') or '').upper()
    if code:
        return code
    alias = str(getattr(product, 'alias', getattr(product, 'name', '')))
    return alias.split('.')[0].upper() if alias else ''


def _fee_fields_from_row(row: Any, source: str) -> dict[str, Any]:
    import pandas as pd
    if row is None:
        return {}

    def num(key: str) -> float | None:
        if key not in row:
            return None
        value = row.get(key)
        return float(value) if pd.notna(value) else None

    return {
        'trading_spec_source': source,
        'trading_spec_date': str(row.get('date', '')) if row.get('date', '') is not None else '',
        'open_fee_ratio': num('open_ratio'),
        'open_fee_fixed': num('open_fixed'),
        'close_fee_ratio': num('close_ratio'),
        'close_fee_fixed': num('close_fixed'),
        'close_today_fee_ratio': num('closetoday_ratio'),
        'close_today_fee_fixed': num('closetoday_fixed'),
        'long_margin_ratio': num('long_margin_ratio'),
        'long_margin_fixed': num('long_margin_fixed'),
        'short_margin_ratio': num('short_margin_ratio'),
        'short_margin_fixed': num('short_margin_fixed'),
        'min_tick': num('min_tick'),
        'point_value': num('multiplier'),
        'min_trade_quantity': num('min_trade_quantity'),
        'max_trade_quantity': num('max_trade_quantity'),
    }


def _fill_missing_trading_spec_fields(product: Any, fields: dict[str, Any]) -> dict[str, Any]:
    """Fill missing Product trading-spec fields one by one."""
    mapping = {
        'open_fee_ratio': 'open_ratio',
        'open_fee_fixed': 'open_fixed',
        'close_fee_ratio': 'close_ratio',
        'close_fee_fixed': 'close_fixed',
        'close_today_fee_ratio': 'closetoday_ratio',
        'close_today_fee_fixed': 'closetoday_fixed',
        'long_margin_ratio': 'long_margin_ratio',
        'long_margin_fixed': 'long_margin_fixed',
        'short_margin_ratio': 'short_margin_ratio',
        'short_margin_fixed': 'short_margin_fixed',
        'min_tick': 'min_tick',
        'point_value': 'multiplier',
        'min_trade_quantity': 'min_trade_quantity',
        'max_trade_quantity': 'max_trade_quantity',
    }
    getter = getattr(product, 'get_trading_spec_field', None)
    if not callable(getter):
        return fields
    filled = False
    for public_key, product_field in mapping.items():
        if fields.get(public_key) not in (None, ''):
            continue
        try:
            value = getter(product_field)
        except Exception:
            value = None
        if value not in (None, ''):
            fields[public_key] = value
            filled = True
    if filled:
        source = str(fields.get('trading_spec_source') or '').strip()
        fields['trading_spec_source'] = (
            f"{source}+openctp_fallback" if source else "openctp_fallback"
        )
    return fields


def cn_futures_trading_spec_fields(product: Any) -> dict[str, Any]:
    """Return current/inferred CN futures trading specs for display.

    Futures uses the current variety-level OpenCTP row. FuturesContract first tries
    contract-level rows, then falls back to the current variety-level row.
    """
    try:
        from sources.LocalCNFutures.FeeData import get_contract_fee_row, load_latest
        import pandas as pd
    except Exception:
        return {}

    try:
        if isinstance(product, FuturesContract):
            contract_row = get_contract_fee_row(getattr(product, 'name', ''), allow_latest_fallback=True)
            if contract_row is not None:
                return _fill_missing_trading_spec_fields(
                    product,
                    _fee_fields_from_row(contract_row, 'current_contract_snapshot'),
                )
            variety = _contract_variety_code(product)
            source = 'current_variety_snapshot_fallback'
        else:
            variety = _future_variety_code(product)
            source = 'current_variety_snapshot'
        if not variety:
            return _fill_missing_trading_spec_fields(product, {})
        df = load_latest()
        if df.empty or 'variety_code' not in df.columns:
            return {}
        match = df[df['variety_code'].astype(str).str.upper() == variety]
        if match.empty:
            return _fill_missing_trading_spec_fields(product, {})
        return _fill_missing_trading_spec_fields(product, _fee_fields_from_row(match.iloc[0], source))
    except Exception:
        return {}


def _serialize_field_value(value: Any) -> Any:
    if value is None or isinstance(value, (str, int, float, bool)):
        return value
    if hasattr(value, 'item'):
        return value.item()
    if isinstance(value, tuple):
        return [_serialize_field_value(v) for v in value]
    if isinstance(value, list) and len(value) <= 20:
        return [_serialize_field_value(v) for v in value]
    if isinstance(value, dict) and len(value) <= 20:
        return {str(k): _serialize_field_value(v) for k, v in value.items()}
    if isinstance(value, type):
        return value.__name__
    return repr(value)


def product_public_fields(product: Any) -> dict[str, Any]:
    """Reflect current backend product fields without a frontend field registry.

    Returns {key: {'value': ..., 'type': 'str'|'int'|'float'|'bool'|'list'|'dict'|...}}
    so the frontend can display both value and type.
    """
    def field_entry(raw_value: Any) -> dict[str, Any]:
        py_type = type(raw_value).__name__
        return {'value': _serialize_field_value(raw_value), 'type': py_type}

    fields: dict[str, Any] = {'class': field_entry(type(product).__name__)}
    for key, value in vars(product).items():
        if key.startswith('_'):
            continue
        fields[key] = field_entry(value)
    # Merge fee/trading-spec fields (already serialized plain values, wrap them)
    fee_fields = cn_futures_trading_spec_fields(product)
    for k, v in fee_fields.items():
        fields[k] = field_entry(v)
    return fields


def supports_adjusted_price(product) -> bool:
    """Whether this product supports adjusted OHLC prices."""
    supports = getattr(product, 'supports_adjusted_price', None)
    if callable(supports):
        return bool(supports())
    return isinstance(product, AdjustableProductMixin)


def supports_term_structure(product) -> bool:
    """Whether this product supports term-structure/contract-chain views."""
    supports = getattr(product, 'supports_term_structure', None)
    if callable(supports):
        return bool(supports())
    return isinstance(product, AdjustableProductMixin)

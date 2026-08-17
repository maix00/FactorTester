"""Service helpers for price viewer and price-series APIs."""

from __future__ import annotations

import os
import re
from functools import lru_cache
from typing import Any, cast

import pandas as pd

from settings import get_all_products
from sources.LocalCNFutures import MINK_PRODUCT_DIR
from sources.LocalCNFutures.CNFutures import (
    CNFuturesContract,
    CNFuturesDayNightTimeCategory,
    CNFuturesSectorCategory,
    CNFuturesSectorNightTimeCategory,
    exchange_map,
    get_all_futures_contract,
)
from tools.data.providers import DataProviderProductTS as DataSource
from tools.products.AdjustableTermStructure import AdjustableProductMixin
from tools.products.Futures import (
    FuturesContract,
    make_contract_category_from_futures_category,
    map_contracts_to_futures,
)
from tools.products.Product import Product
from tools.products.categories.Category import CategoryTree, combine_trees
from server.services.product_tree import build_classifier_tree
from tools.traderules import exchange_rule_manifest_for_product


@lru_cache(maxsize=1)
def cached_products():
    return tuple(get_all_products())


@lru_cache(maxsize=1)
def cached_contracts():
    return tuple(get_all_futures_contract())


@lru_cache(maxsize=1)
def cached_product_tree() -> CategoryTree:
    return build_product_tree()


CN_FUTURES_DAY_NIGHT_CATEGORY_ID = "cnfutures_day_night"
CN_FUTURES_SECTOR_CATEGORY_ID = "cnfutures_sector"
CN_FUTURES_COMPOSITE_CATEGORY_ID = (
    f"{CN_FUTURES_DAY_NIGHT_CATEGORY_ID}×{CN_FUTURES_SECTOR_CATEGORY_ID}"
)


_BASE_PRODUCT_CATEGORY_DEFINITIONS = (
    {
        "id": CN_FUTURES_DAY_NIGHT_CATEGORY_ID,
        "alias": "中国期货日夜盘",
        "title_zh": "中国期货日夜盘",
        "source_ids": ("Local",),
        "dimensions": (CN_FUTURES_DAY_NIGHT_CATEGORY_ID,),
        "composable": True,
        "is_composite": False,
        "kind": "source",
        "owner_ref": "source",
        "source_managed": True,
        "items": (),
    },
    {
        "id": CN_FUTURES_SECTOR_CATEGORY_ID,
        "alias": "中国期货行业",
        "title_zh": "中国期货行业",
        "source_ids": ("Local",),
        "dimensions": (CN_FUTURES_SECTOR_CATEGORY_ID,),
        "composable": True,
        "is_composite": False,
        "kind": "source",
        "owner_ref": "source",
        "source_managed": True,
        "items": (),
    },
)

_BASE_PRODUCT_CATEGORY_TYPES = {
    CN_FUTURES_DAY_NIGHT_CATEGORY_ID: CNFuturesDayNightTimeCategory,
    CN_FUTURES_SECTOR_CATEGORY_ID: CNFuturesSectorCategory,
}


def available_product_categories() -> list[dict[str, Any]]:
    """Return provider-defined base dimensions that the product UI may compose."""
    return [
        dict(
            item,
            dimensions=list(item["dimensions"]),
            source_ids=list(item.get("source_ids") or []),
            items=list(item.get("items") or []),
        )
        for item in _BASE_PRODUCT_CATEGORY_DEFINITIONS
    ]


def normalize_product_category_id(category_id: str | None) -> str:
    """Return the canonical id for one or more registered base Categories."""
    raw = str(category_id or "").strip().lower()
    if not raw:
        raise ValueError("未选择产品分类")
    parts = _split_product_category_id(
        raw,
        tuple(_BASE_PRODUCT_CATEGORY_TYPES),
    )
    if parts is None or len(set(parts)) != len(parts):
        raise ValueError(f"不支持的产品分类: {category_id}")
    requested = set(parts)
    canonical = tuple(
        category_ref
        for category_ref in _BASE_PRODUCT_CATEGORY_TYPES
        if category_ref in requested
    )
    if set(canonical) != requested:
        raise ValueError(f"不支持的产品分类: {category_id}")
    return "×".join(canonical)


def _split_product_category_id(
    value: str,
    base_ids: tuple[str, ...],
) -> tuple[str, ...] | None:
    if value in base_ids:
        return (value,)
    for category_ref in sorted(base_ids, key=len, reverse=True):
        prefix = f"{category_ref}×"
        if value.startswith(prefix):
            remainder = _split_product_category_id(value[len(prefix):], base_ids)
            if remainder is not None:
                return (category_ref, *remainder)
    return None


def _futures_category_for_id(category_id: str):
    normalized = normalize_product_category_id(category_id)
    dimensions = _split_product_category_id(
        normalized,
        tuple(_BASE_PRODUCT_CATEGORY_TYPES),
    )
    if not dimensions:
        raise ValueError(f"不支持的产品分类: {category_id}")
    category = _BASE_PRODUCT_CATEGORY_TYPES[dimensions[0]]
    for dimension in dimensions[1:]:
        category = category * _BASE_PRODUCT_CATEGORY_TYPES[dimension]
    return category


def contract_data_path(contract_uid: str) -> str:
    return os.path.join(MINK_PRODUCT_DIR, f"{contract_uid}.parquet")


def contract_has_data(contract_uid: str) -> bool:
    return os.path.isfile(contract_data_path_for(contract_uid))


def scalar(value: Any) -> Any:
    return value.item() if hasattr(value, 'item') else value


def timestamp_or_none(value: Any) -> pd.Timestamp | None:
    value = scalar(value)
    if pd.isna(value):
        return None
    return cast(pd.Timestamp, pd.Timestamp(value))


def build_product_tree() -> CategoryTree:
    """Build the default catalog without applying any Category projection."""
    return build_classifier_tree([
        *cached_products(),
        *cached_contracts(),
    ])


@lru_cache(maxsize=8)
def cached_product_tree_for_category(category_id: str) -> CategoryTree:
    """Build one product tree for one explicit, stable category id."""
    normalized = normalize_product_category_id(category_id)
    product_tree = _futures_category_for_id(normalized).get_tree(
        ancester=Product,
    )
    contracts = list(cached_contracts())
    contract_tree = get_contract_category_tree(contracts, normalized)
    return combine_trees(product_tree, contract_tree)


def get_contract_category_tree(contracts, category_id: str | None = None) -> CategoryTree:
    """Build a CNFuturesContract tree that mirrors CNFutures category labels."""
    contract_to_future = map_contracts_to_futures_for_categories(contracts)

    category = make_contract_category_from_futures_category(
        CNFuturesSectorNightTimeCategory if category_id is None else _futures_category_for_id(category_id),
        CNFuturesContract,
        contracts,
        contract_to_future,
    )
    tree_builder = category.get_tree if category_id is not None else category.get_tree_with_parents
    return tree_builder(all_objects=contracts, ancester=Product)


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
            for source in DataSource.available_for_product(product, data_freq):
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
    """Find a product through source-owned naming rules."""
    wanted = str(product_name or '').strip()
    products = tuple(products)

    def exact(value: str):
        return next((product for product in products if product is not None and (
            getattr(product, 'name', None) == value or
            getattr(product, 'alias', None) == value
        )), None)

    product = exact(wanted)
    if product is not None:
        return product
    for source in DataSource.all():
        resolver = getattr(source, 'resolve_reference', None)
        if not callable(resolver):
            continue
        try:
            canonical = resolver(wanted)
        except (TypeError, ValueError, OSError, RuntimeError):
            continue
        if canonical and canonical != wanted:
            product = exact(str(canonical))
            if product is not None:
                return product
    return None


def find_contract_product(contract_uid):
    """Resolve a logical contract reference through source-owned naming rules."""
    wanted = str(contract_uid or '').strip()
    contracts = cached_contracts()

    def exact(value: str):
        return next((contract for contract in contracts if contract is not None and (
            getattr(contract, 'name', None) == value or
            getattr(contract, 'alias', None) == value
        )), None)

    product = exact(wanted)
    if product is not None:
        return product
    for source in DataSource.all():
        resolver = getattr(source, 'resolve_reference', None)
        if not callable(resolver):
            continue
        try:
            canonical = resolver(wanted)
        except (TypeError, ValueError, OSError, RuntimeError):
            continue
        if canonical and canonical != wanted:
            product = exact(str(canonical))
            if product is not None:
                return product
    return None


def contract_data_path_for(
    contract_uid: str,
    contract_product: Any | None = None,
) -> str:
    """Resolve a contract file through its data source before legacy fallback."""
    product = contract_product or find_contract_product(contract_uid)
    if product is not None:
        for source in DataSource.available_for_product(product):
            try:
                path = str(source.get_path(product) or '')
            except (OSError, RuntimeError, TypeError, ValueError):
                continue
            if path and os.path.isfile(path):
                return path
    return contract_data_path(contract_uid)


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


def reflect_public_fields(obj: Any, *, extra: dict[str, Any] | None = None) -> dict[str, Any]:
    """Reflect an arbitrary backend object's public fields without a frontend field registry.

    Returns {key: {'value': ..., 'type': 'str'|'int'|'float'|'bool'|'list'|'dict'|...}}
    so the frontend can display both value and type. Any backend object with a
    `__dict__` (products, factor expressions, ...) can be reflected this way.
    """
    def field_entry(raw_value: Any) -> dict[str, Any]:
        py_type = type(raw_value).__name__
        return {'value': _serialize_field_value(raw_value), 'type': py_type}

    fields: dict[str, Any] = {'class': field_entry(type(obj).__name__)}
    for key, value in vars(obj).items():
        if key.startswith('_'):
            continue
        fields[key] = field_entry(value)
    for k, v in (extra or {}).items():
        fields[k] = field_entry(v)
    return fields


def _exchange_rule_fields(product: Any) -> dict[str, dict[str, Any]]:
    manifest = exchange_rule_manifest_for_product(product)
    if not manifest:
        return {}
    source_label = str(manifest.get('label') or manifest.get('provider') or '交易所默认规则')
    rule_note = str(manifest.get('note') or '')
    fields: dict[str, dict[str, Any]] = {}
    for item in manifest.get('fields', []):
        if not isinstance(item, dict):
            continue
        key = str(item.get('key') or '')
        if not key:
            continue
        item_note = str(item.get('note') or '')
        fields[key] = {
            'value': _serialize_field_value(item.get('value')),
            'type': type(item.get('value')).__name__,
            'label': item.get('label') or key,
            'note': item_note,
            'source': source_label,
            'source_note': rule_note,
        }
    return fields


def product_public_fields(product: Any) -> dict[str, Any]:
    """Reflect current backend product fields (class, public attrs, fee/trading-spec fields)."""
    fields = reflect_public_fields(product, extra=cn_futures_trading_spec_fields(product))
    fields.update(_exchange_rule_fields(product))
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

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
def cached_price_viewer_tree() -> CategoryTree:
    return build_price_viewer_tree()


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


def build_price_viewer_tree() -> CategoryTree:
    """价格页产品树：原品种分类 + 合约类型继承链。"""
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
                    'alias': source.alias,
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

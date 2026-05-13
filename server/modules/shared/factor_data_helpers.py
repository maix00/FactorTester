"""Helper utilities for shared factor data routes."""

from __future__ import annotations

from types import SimpleNamespace
from typing import cast
import numpy as np
import pandas as pd


def match_product_column(table: pd.DataFrame | None, product) -> object | None:
    """Match product column in DataFrame where columns may be Product objects or names."""
    if not isinstance(table, pd.DataFrame) or table.empty:
        return None
    if product in table.columns:
        return product
    target_name = getattr(product, 'name', str(product))
    target_alias = getattr(product, 'alias', target_name)
    for col in table.columns:
        col_name = getattr(col, 'name', str(col))
        col_alias = getattr(col, 'alias', col_name)
        if str(col_name) == str(target_name) or str(col_alias) == str(target_alias):
            return col
    return None


def column_names(table: pd.DataFrame | None) -> list[str]:
    if not isinstance(table, pd.DataFrame) or table.empty:
        return []
    return [str(getattr(c, 'name', c)) for c in table.columns]


def find_factor(factors, factor_name: str | None, factor_alias: str | None):
    if factor_alias not in (None, ''):
        by_alias = next((f for f in factors if f.alias == factor_alias), None)
        if by_alias is not None:
            return by_alias
    if factor_name not in (None, ''):
        return next((f for f in factors if f.name == factor_name or f.alias == factor_name), None)
    return None


def resolve_fe_table(tester_factor, tester=None) -> pd.DataFrame | None:
    """Read FE table from FactorRunResult.func_table (IC test intermediate).
    
    func_table = _func_expr.evaluate() result: includes $Rev (if applicable), no SignalAlign.
    """
    if tester is not None and hasattr(tester, 'results'):
        r = tester.results.get(tester_factor)
        if r is not None and not r.func_table.empty:
            return r.func_table
    return None


def resolve_product_from_tester(tester, product_name: str):
    product = next((p for p in tester.products if p.name == product_name), None)
    if not product:
        product = SimpleNamespace(name=product_name, alias=product_name)
    return product


def find_tester_product(tester, product_name: str):
    """Find real product object from tester; return None if not found."""
    return next((p for p in tester.products if getattr(p, 'name', None) == product_name), None)


def clip_series_by_tester_range(series, tester):
    def _get_idx(s):
        return s.index.get_level_values(-1) if isinstance(s.index, pd.MultiIndex) else s.index

    def _loc(ts, idx):
        tz = getattr(idx, 'tz', None)
        return ts.tz_localize(tz) if tz and ts.tzinfo is None else (
            ts.replace(tzinfo=None) if not tz and ts.tzinfo else ts)

    idx = _get_idx(series)
    if tester.start_date is not None:
        series = series[idx >= _loc(pd.Timestamp(tester.start_date), idx)]
        idx = _get_idx(series)
    if tester.end_date is not None:
        series = series[idx <= _loc(pd.Timestamp(tester.end_date), idx)]
    return series


def series_to_frontend(series, is_daily: bool):
    idx = series.index.get_level_values(-1) if isinstance(series.index, pd.MultiIndex) else series.index
    if is_daily:
        dates_out = [ts.strftime('%Y-%m-%d') for ts in idx]
    else:
        raw = cast(np.ndarray, idx.view(np.int64))
        dates_out = cast('list[int]', (raw // 10**6).tolist())
    values = [None if (isinstance(v, float) and (pd.isna(v) or np.isinf(v))) else v
              for v in series.values.tolist()]
    return dates_out, values

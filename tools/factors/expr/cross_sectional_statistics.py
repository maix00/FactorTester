"""Cross-sectional IC statistics kept separate from expression-tree dispatch."""
from __future__ import annotations

import numpy as np
import pandas as pd


def _empty(index: pd.Index) -> pd.DataFrame:
    return pd.DataFrame({"IC": pd.Series(dtype=float)}, index=index[:0])


def _restore(result: pd.DataFrame, source: pd.Index) -> pd.DataFrame:
    if isinstance(source, pd.MultiIndex):
        if isinstance(result.index, pd.MultiIndex) and result.index.nlevels == source.nlevels:
            result.index.names = source.names
        elif len(result.index) and all(isinstance(v, tuple) and len(v) == source.nlevels for v in result.index):
            result.index = pd.MultiIndex.from_tuples(result.index, names=source.names)
    elif not isinstance(result.index, pd.MultiIndex):
        result.index.name = source.name
    return result


def _rank_rows_average(values: np.ndarray, valid: np.ndarray) -> np.ndarray:
    """Average-rank each row without constructing pandas rank DataFrames.

    IC panels usually have only a handful of products but hundreds of
    thousands of signal rows.  For that shape, the exact ``method='average'``
    rank can be expressed with pairwise counts: rank(x) is one plus the
    number of valid values below x, plus half the number of tied peers.  The
    column loop is bounded by the cross-section width, so it avoids pandas'
    per-row DataFrame machinery while preserving NaN/duplicate semantics.
    """

    row_count, column_count = values.shape
    ranked = np.full((row_count, column_count), np.nan, dtype=float)
    for column in range(column_count):
        current = values[:, column]
        current_valid = valid[:, column]
        less = np.sum(valid & (values < current[:, None]), axis=1)
        equal = np.sum(valid & (values == current[:, None]), axis=1)
        ranked[current_valid, column] = (
            less[current_valid] + 0.5 * (equal[current_valid] + 1.0)
        )
    return ranked


def correlation(left: pd.DataFrame, right: pd.DataFrame, *, spearman: bool) -> pd.DataFrame:
    if left.index.equals(right.index) and left.columns.equals(right.columns):
        idx, l_df, r_df = left.index, left, right
    else:
        idx = pd.Index(left.index).intersection(pd.Index(right.index))
        cols = left.columns.intersection(right.columns)
        if not len(idx) or not len(cols):
            return _empty(left.index)
        l_df, r_df = left.loc[idx, cols], right.loc[idx, cols]
    valid = l_df.notna() & r_df.notna()
    if spearman:
        # The strict product panel is small (six products in the current
        # research trial).  Use a NumPy rank kernel for small cross-sections;
        # retain pandas' general path for unusually wide panels.
        if l_df.shape[1] <= 16:
            valid_array = valid.to_numpy(dtype=bool, copy=False)
            l_values = l_df.to_numpy(dtype=float, copy=False)
            r_values = r_df.to_numpy(dtype=float, copy=False)
            x = _rank_rows_average(l_values, valid_array)
            y = _rank_rows_average(r_values, valid_array)
        else:
            l_df = l_df.where(valid).rank(axis=1, method="average", na_option="keep")
            r_df = r_df.where(valid).rank(axis=1, method="average", na_option="keep")
            x, y = l_df.to_numpy(dtype=float), r_df.to_numpy(dtype=float)
    else:
        x, y = l_df.to_numpy(dtype=float), r_df.to_numpy(dtype=float)
    mask = ~np.isnan(x) & ~np.isnan(y)
    x, y = np.where(mask, x, 0.0), np.where(mask, y, 0.0)
    n = mask.sum(axis=1).astype(float)
    sx, sy, sx2, sy2, sxy = x.sum(1), y.sum(1), (x*x).sum(1), (y*y).sum(1), (x*y).sum(1)
    numerator = n * sxy - sx * sy
    denominator = np.sqrt((n * sx2 - sx * sx) * (n * sy2 - sy * sy))
    with np.errstate(divide="ignore", invalid="ignore"):
        ic = numerator / denominator
    ic[(n <= 1) | (denominator <= 0)] = np.nan
    return _restore(pd.DataFrame({"IC": ic}, index=idx), left.index)

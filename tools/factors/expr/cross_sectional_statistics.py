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
        l_df = l_df.where(valid).rank(axis=1, method="average", na_option="keep")
        r_df = r_df.where(valid).rank(axis=1, method="average", na_option="keep")
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

"""Cross-sectional IC statistics kept separate from expression-tree dispatch."""
from __future__ import annotations

from contextlib import contextmanager
from contextvars import ContextVar
import numpy as np
import pandas as pd

_capture_spearman_ranks = ContextVar("capture_spearman_ranks", default=False)


@contextmanager
def capture_spearman_rank_panels(enabled: bool = True):
    token = _capture_spearman_ranks.set(bool(enabled))
    try:
        yield
    finally:
        _capture_spearman_ranks.reset(token)


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

    # Rank a bounded row block at a time.  Lexicographic sorting places valid
    # values first and is O(rows * columns * log(columns)); the old pairwise
    # count kernel was O(rows * columns**2) and became the dominant cost for
    # 25-product intraday IC panels.  Stable sorting plus the group boundaries
    # below reproduces pandas' ``method='average', na_option='keep'`` ranks.
    block_rows = max(1, min(row_count, 65_536))
    for start in range(0, row_count, block_rows):
        stop = min(row_count, start + block_rows)
        block = np.asarray(values[start:stop], dtype=float)
        block_valid = np.asarray(valid[start:stop], dtype=bool)
        # ``lexsort`` uses the last key as primary: valid (0) before invalid
        # (1), then ascending numeric value among valid columns.
        order = np.lexsort(
            (np.where(block_valid, block, 0.0), (~block_valid).astype(np.int8)),
            axis=1,
        )
        sorted_values = np.take_along_axis(block, order, axis=1)
        sorted_valid = np.take_along_axis(block_valid, order, axis=1)
        counts = np.cumsum(sorted_valid, axis=1, dtype=float)
        previous_valid = np.concatenate(
            (np.zeros((sorted_valid.shape[0], 1), dtype=bool), sorted_valid[:, :-1]),
            axis=1,
        )
        next_valid = np.concatenate(
            (sorted_valid[:, 1:], np.zeros((sorted_valid.shape[0], 1), dtype=bool)),
            axis=1,
        )
        previous_values = np.concatenate(
            (np.zeros((sorted_values.shape[0], 1), dtype=float), sorted_values[:, :-1]),
            axis=1,
        )
        next_values = np.concatenate(
            (sorted_values[:, 1:], np.zeros((sorted_values.shape[0], 1), dtype=float)),
            axis=1,
        )
        starts = sorted_valid & (
            ~previous_valid | (sorted_values != previous_values)
        )
        ends = sorted_valid & (
            ~next_valid | (sorted_values != next_values)
        )
        # Store less-count + 1 so the first group (whose less-count is zero)
        # survives the forward maximum fill.
        start_markers = np.where(starts, counts, 0.0)
        less_count = np.maximum.accumulate(start_markers, axis=1) - 1.0
        end_markers = np.where(ends, counts, np.inf)
        end_count = np.minimum.accumulate(end_markers[:, ::-1], axis=1)[:, ::-1]
        sorted_ranks = np.where(
            sorted_valid,
            (less_count + 1.0 + end_count) / 2.0,
            np.nan,
        )
        np.put_along_axis(ranked[start:stop], order, sorted_ranks, axis=1)
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
        # A NumPy stable-sort rank kernel is materially faster for the bounded
        # product panels used by IC tests (including the 25-product night
        # sample); retain pandas' general path for unusually wide panels.
        if l_df.shape[1] <= 64:
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
    captured = None
    if spearman and _capture_spearman_ranks.get():
        counts = mask.sum(axis=1).astype(float)
        denominator_rank = np.where(counts > 0, counts, np.nan)[:, None]
        captured = (
            pd.DataFrame(x / denominator_rank - 0.5, index=idx, columns=l_df.columns),
            pd.DataFrame(y / denominator_rank - 0.5, index=idx, columns=r_df.columns),
        )
    x, y = np.where(mask, x, 0.0), np.where(mask, y, 0.0)
    n = mask.sum(axis=1).astype(float)
    sx, sy, sx2, sy2, sxy = x.sum(1), y.sum(1), (x*x).sum(1), (y*y).sum(1), (x*y).sum(1)
    numerator = n * sxy - sx * sy
    denominator = np.sqrt((n * sx2 - sx * sx) * (n * sy2 - sy * sy))
    with np.errstate(divide="ignore", invalid="ignore"):
        ic = numerator / denominator
    ic[(n <= 1) | (denominator <= 0)] = np.nan
    result = _restore(pd.DataFrame({"IC": ic}, index=idx), left.index)
    if captured is not None:
        result.attrs["factor_cs_rank"] = _restore(captured[0], left.index)
        result.attrs["return_cs_rank"] = _restore(captured[1], right.index)
    return result

"""Small NumPy kernels for product-level cross-sectional transforms.

The batch expression layer uses pandas for alignment and public semantics.  A
live executor already has one dense product vector, so constructing a Series
and its index on every bar is avoidable.  These kernels intentionally mirror
the pandas defaults used by :mod:`tools.factors.expr.cross_sectional`:

* ranks use average ties and a denominator equal to the non-missing count;
* ordinal ranks use stable first-occurrence ordering;
* standard deviation uses sample ``ddof=1``;
* NaN is missing, while +/-Inf remains an observed value for these operators.
"""

from __future__ import annotations

import numpy as np


def _valid_values(values: np.ndarray, eligible: np.ndarray | None = None) -> np.ndarray:
    """Return the pandas-compatible observation mask for a float vector."""

    valid = ~np.isnan(values)
    if eligible is not None:
        valid &= np.asarray(eligible, dtype=bool)
    return valid


def rank_percent(
    values: np.ndarray,
    eligible: np.ndarray | None = None,
) -> np.ndarray:
    """Return ``Series.rank(pct=True) - .5`` for one product cross-section."""

    values = np.asarray(values, dtype=float)
    valid = _valid_values(values, eligible)
    result = np.full(values.shape, np.nan, dtype=float)
    indices = np.flatnonzero(valid)
    if indices.size == 0:
        return result

    observed = values[indices]
    order = np.argsort(observed, kind="mergesort")
    sorted_values = observed[order]
    starts = np.r_[0, np.flatnonzero(sorted_values[1:] != sorted_values[:-1]) + 1]
    ends = np.r_[starts[1:], len(sorted_values)]
    average_ranks = (starts + ends - 1) / 2.0 + 1.0
    ranks = np.repeat(average_ranks, np.diff(np.r_[starts, len(sorted_values)]))
    result[indices[order]] = ranks / indices.size - 0.5
    return result


def ordinal_rank(
    values: np.ndarray,
    eligible: np.ndarray,
    tie_break_order: np.ndarray,
    *,
    ascending: bool,
) -> np.ndarray:
    """Return pandas ``rank(method='first')`` after stable index ordering."""

    values = np.asarray(values, dtype=float)
    valid = _valid_values(values, eligible)
    result = np.full(values.shape, np.nan, dtype=float)
    ordered_indices = tie_break_order[valid[tie_break_order]]
    if ordered_indices.size == 0:
        return result

    observed = values[ordered_indices]
    sort_values = observed if ascending else -observed
    by_value = np.argsort(sort_values, kind="mergesort")
    result[ordered_indices[by_value]] = np.arange(1, ordered_indices.size + 1, dtype=float)
    return result


def zscore(values: np.ndarray, eligible: np.ndarray | None = None) -> np.ndarray:
    """Return pandas row z-score with the default sample standard deviation."""

    values = np.asarray(values, dtype=float)
    valid = _valid_values(values, eligible)
    result = np.full(values.shape, np.nan, dtype=float)
    observed = values[valid]
    if observed.size < 2:
        return result

    with np.errstate(all="ignore"):
        mean = observed.mean()
        std = observed.std(ddof=1)
    if std == 0.0:
        result[valid] = 0.0
    else:
        with np.errstate(all="ignore"):
            result[valid] = (observed - mean) / std
    return result


def demean(values: np.ndarray, eligible: np.ndarray | None = None) -> np.ndarray:
    """Return pandas ``Series - Series.mean()`` for one cross-section."""

    values = np.asarray(values, dtype=float)
    valid = _valid_values(values, eligible)
    result = np.full(values.shape, np.nan, dtype=float)
    observed = values[valid]
    if observed.size == 0:
        return result
    with np.errstate(all="ignore"):
        result[valid] = observed - observed.mean()
    return result

"""Chunked batch kernel for rolling median absolute deviation."""

from __future__ import annotations

import numpy as np
import pandas as pd
from numpy.lib.stride_tricks import sliding_window_view

_MAX_TEMPORARY_BYTES = 8 * 1024 * 1024
_TEMPORARY_ARRAYS_PER_VALUE = 4


def rolling_mad_batch(
    data: pd.DataFrame,
    window: int,
    *,
    min_periods: int | None = None,
) -> pd.DataFrame:
    """Compute rolling MAD in bounded NumPy chunks, preserving pandas semantics."""
    if window < 1:
        raise ValueError("window must be at least 1")
    if min_periods is None:
        min_periods = max(1, window // 2)
    if min_periods < 1 or min_periods > window:
        raise ValueError("min_periods must be between 1 and window")

    values = data.to_numpy(dtype=float, copy=False)
    row_count, product_count = values.shape
    if row_count == 0 or product_count == 0:
        return pd.DataFrame(
            np.full(values.shape, np.nan), index=data.index, columns=data.columns
        )

    padded = np.pad(values, ((window - 1, 0), (0, 0)), constant_values=np.nan)
    windows = sliding_window_view(padded, window_shape=window, axis=0)
    result = np.full(values.shape, np.nan, dtype=float)

    max_elements = max(
        1,
        _MAX_TEMPORARY_BYTES
        // (np.dtype(float).itemsize * _TEMPORARY_ARRAYS_PER_VALUE),
    )
    product_chunk = max(1, min(product_count, max_elements // window))
    row_chunk = max(1, max_elements // (product_chunk * window))

    for product_start in range(0, product_count, product_chunk):
        product_stop = min(product_count, product_start + product_chunk)
        for row_start in range(0, row_count, row_chunk):
            row_stop = min(row_count, row_start + row_chunk)
            block = windows[row_start:row_stop, product_start:product_stop, :]
            counts = np.isfinite(block).sum(axis=-1)
            active_positions = np.argwhere(counts >= min_periods)
            if active_positions.size == 0:
                continue

            active_windows = block[active_positions[:, 0], active_positions[:, 1], :]
            active_windows = np.where(
                np.isfinite(active_windows), active_windows, np.nan
            )
            medians = np.nanmedian(active_windows, axis=-1)
            deviations = np.abs(active_windows - medians[:, None])
            mad = np.nanmedian(deviations, axis=-1)

            result[
                row_start + active_positions[:, 0],
                product_start + active_positions[:, 1],
            ] = mad

    return pd.DataFrame(result, index=data.index, columns=data.columns)

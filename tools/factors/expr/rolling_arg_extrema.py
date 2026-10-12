"""Bounded-memory batch kernels for rolling argmax and argmin."""

from __future__ import annotations

import numpy as np
import pandas as pd

_ARG_EXTREMA_TEMP_BUDGET_BYTES = 8 * 1024 * 1024


def rolling_argmaxmin(
    df: pd.DataFrame,
    window: int,
    op: str,
    normalize: bool = True,
    trunc_start: np.ndarray | None = None,
    trunc_end: np.ndarray | None = None,
) -> pd.DataFrame:
    """Compute each column's rolling arg-extreme using bounded row chunks."""
    if window < 1:
        raise ValueError(f"window must be >= 1, got {window}")

    n_rows = len(df)
    if window == 1:
        values = df.to_numpy(dtype=float)
        result = np.where(np.isnan(values), np.nan, 0.0)
        return pd.DataFrame(result, index=df.index, columns=df.columns)

    n_cols = df.shape[1]
    if n_rows < window:
        return pd.DataFrame(
            np.full((n_rows, n_cols), np.nan),
            index=df.index,
            columns=df.columns,
        )
    if op not in {
        "rolling_argmax",
        "rolling_argmax_raw",
        "rolling_argmin",
        "rolling_argmin_raw",
    }:
        raise ValueError(f"Invalid op: {op}")

    values = df.to_numpy(dtype=float, copy=False)
    n_windows = n_rows - window + 1
    windows = np.lib.stride_tricks.sliding_window_view(values, window, axis=0)
    has_truncation = trunc_start is not None or trunc_end is not None
    # Account for materialized values, masks, and overlapping integer/float
    # position arrays while a chunk is being transformed.
    bytes_per_cell = 32 if has_truncation else 24
    row_bytes = max(1, n_cols * window * bytes_per_cell)
    chunk_rows = max(1, _ARG_EXTREMA_TEMP_BUDGET_BYTES // row_bytes)
    positions = np.empty((n_windows, n_cols), dtype=float)
    window_indices = np.arange(window).reshape(1, 1, window)
    is_max = op in {"rolling_argmax", "rolling_argmax_raw"}
    missing_fill = -np.inf if is_max else np.inf

    for first in range(0, n_windows, chunk_rows):
        last = min(n_windows, first + chunk_rows)
        block = windows[first:last]
        if has_truncation:
            outside = None
            if trunc_start is not None:
                outside = window_indices < trunc_start[first:last, :, np.newaxis]
            if trunc_end is not None:
                after_end = window_indices > trunc_end[first:last, :, np.newaxis]
                outside = after_end if outside is None else outside | after_end
            block = np.where(outside, np.nan, block)

        # Reversal keeps the current tie contract: the most recent match wins.
        reversed_view = block[..., ::-1]
        missing = np.isnan(reversed_view)
        all_missing = np.all(missing, axis=-1)
        safe_values = np.where(missing, missing_fill, reversed_view)
        extreme_positions = (
            np.argmax(safe_values, axis=-1)
            if is_max
            else np.argmin(safe_values, axis=-1)
        )
        # A full all-NaN window has the neutral position 0 in both backends.
        extreme_positions[all_missing] = window - 1
        chunk_positions = (window - 1) - extreme_positions
        if normalize:
            chunk_positions = chunk_positions / (window - 1)
        positions[first:last] = chunk_positions

    warmup = np.full((window - 1, n_cols), np.nan)
    result = np.vstack([warmup, positions])
    return pd.DataFrame(result, index=df.index, columns=df.columns)

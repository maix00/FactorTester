from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

import tools.factors.expr.rolling_mad as rolling_mad_module
from tools.factors.expr.rolling_mad import rolling_mad_batch


def _pandas_reference(
    values: pd.DataFrame,
    window: int,
    min_periods: int,
) -> pd.DataFrame:
    return values.rolling(window, min_periods=min_periods).apply(
        lambda sample: np.nanmedian(np.abs(sample - np.nanmedian(sample))),
        raw=True,
    )


@pytest.mark.parametrize("window", [1, 2, 3, 17, 63])
def test_batch_rolling_mad_matches_pandas_with_partial_windows_and_missing_values(
    window: int,
) -> None:
    rng = np.random.default_rng(821)
    values = rng.normal(size=(139, 5))
    values[::11, 1] = np.nan
    values[::13, 2] = np.inf
    values[::17, 3] = -np.inf
    values[:, 4] = 7.0
    frame = pd.DataFrame(
        values,
        index=pd.date_range("2026-01-01", periods=len(values), freq="min"),
        columns=["near", "gap", "positive-inf", "negative-inf", "constant"],
    )
    min_periods = max(1, window // 2)

    actual = rolling_mad_batch(frame, window, min_periods=min_periods)
    expected = _pandas_reference(frame, window, min_periods)

    pd.testing.assert_frame_equal(
        actual, expected, check_exact=False, rtol=1e-12, atol=1e-12
    )


def test_batch_rolling_mad_preserves_index_and_column_order() -> None:
    frame = pd.DataFrame(
        {"second": [4.0, 1.0, 9.0], "first": [2.0, 8.0, 3.0]},
        index=pd.Index(["a", "b", "c"], name="observation"),
    )

    actual = rolling_mad_batch(frame, 2, min_periods=1)

    assert actual.index.equals(frame.index)
    assert actual.columns.equals(frame.columns)


def test_batch_rolling_mad_keeps_results_across_memory_chunks(monkeypatch) -> None:
    rng = np.random.default_rng(423)
    values = rng.normal(size=(41, 7))
    values[::5, 2] = np.nan
    frame = pd.DataFrame(values)
    window = 7
    min_periods = 3
    expected = _pandas_reference(frame, window, min_periods)
    monkeypatch.setattr(rolling_mad_module, "_MAX_TEMPORARY_BYTES", 1024)

    actual = rolling_mad_batch(frame, window, min_periods=min_periods)

    pd.testing.assert_frame_equal(
        actual,
        expected,
        check_exact=False,
        rtol=1e-12,
        atol=1e-12,
    )

from __future__ import annotations

import numpy as np
import pandas as pd

from tools.factors.expr.cross_sectional_statistics import (
    _rank_rows_average,
    capture_spearman_rank_panels,
    correlation,
)


def test_numpy_row_rank_matches_pandas_average_rank_for_wide_tied_panels() -> None:
    rng = np.random.default_rng(141)
    values = rng.integers(-3, 4, size=(128, 25)).astype(float)
    values[rng.random(values.shape) < 0.1] = np.nan
    valid = np.isfinite(values)

    actual = _rank_rows_average(values, valid)
    expected = pd.DataFrame(values).rank(
        axis=1, method="average", na_option="keep",
    ).to_numpy()

    np.testing.assert_allclose(actual, expected, equal_nan=True)


def test_spearman_capture_reuses_exact_rank_operands_as_cs_rank_panels() -> None:
    index = pd.date_range("2026-01-01", periods=2)
    left = pd.DataFrame([[1.0, 2.0, 2.0], [4.0, np.nan, 1.0]], index=index,
                        columns=["A", "B", "C"])
    right = pd.DataFrame([[3.0, 1.0, 2.0], [2.0, 5.0, 1.0]], index=index,
                         columns=["A", "B", "C"])

    with capture_spearman_rank_panels():
        result = correlation(left, right, spearman=True)

    expected_factor = left.where(left.notna() & right.notna()).rank(
        axis=1, method="average", pct=True,
    ) - 0.5
    expected_return = right.where(left.notna() & right.notna()).rank(
        axis=1, method="average", pct=True,
    ) - 0.5
    pd.testing.assert_frame_equal(result.attrs["factor_cs_rank"], expected_factor)
    pd.testing.assert_frame_equal(result.attrs["return_cs_rank"], expected_return)


def test_spearman_does_not_retain_rank_panels_unless_artifact_requested() -> None:
    values = pd.DataFrame([[1.0, 2.0]], columns=["A", "B"])
    result = correlation(values, values, spearman=True)
    assert "factor_cs_rank" not in result.attrs
    assert "return_cs_rank" not in result.attrs

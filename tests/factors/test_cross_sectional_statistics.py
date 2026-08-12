from __future__ import annotations

import numpy as np
import pandas as pd

from tools.factors.expr.cross_sectional_statistics import _rank_rows_average


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

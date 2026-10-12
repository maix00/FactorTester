from __future__ import annotations

import numpy as np
import pytest

from tools.factors.expr.rolling_regression import (
    ROLLING_LINEAR_METRICS,
    linear_metric,
)
from tools.factors.expr.rolling_regression_state import RollingLinearState


@pytest.mark.parametrize("metric", sorted(ROLLING_LINEAR_METRICS))
@pytest.mark.parametrize("window", [3, 4, 17, 63])
def test_incremental_linear_state_matches_ols_for_every_bar_and_product(
    metric: str,
    window: int,
) -> None:
    rng = np.random.default_rng(912)
    values = rng.normal(loc=10_000.0, scale=3.0, size=(311, 4))
    values[::9, 0] = np.nan
    values[::13, 1] = np.inf
    values[::17, 2] = -np.inf
    values[:, 3] = 0.0
    minimum = max(3, window // 2)
    state = RollingLinearState(window, values.shape[1], metric)

    history: list[np.ndarray] = []
    for current in values:
        history.append(current.copy())
        actual = state.update(current)
        expected = np.array(
            [
                linear_metric(
                    np.asarray(history[-window:])[:, column],
                    metric,
                    minimum,
                )
                for column in range(values.shape[1])
            ]
        )

        # t-statistics amplify tiny residual round-off when a short window is
        # nearly linear; other metrics retain the tighter parity tolerance.
        relative_tolerance = 1e-5 if metric == "rolling_linreg_tstat" else 2e-9
        np.testing.assert_allclose(
            actual,
            expected,
            rtol=relative_tolerance,
            atol=2e-9,
            equal_nan=True,
        )


def test_incremental_linear_state_rejects_a_changed_product_width() -> None:
    state = RollingLinearState(window=5, width=2, metric="rolling_linreg_slope")

    with pytest.raises(ValueError, match="width"):
        state.update(np.array([1.0]))


def test_incremental_linear_state_stays_stable_across_long_high_level_series() -> None:
    rng = np.random.default_rng(423_01)
    values = 1.0e12 + np.arange(4300, dtype=float) * 0.25
    values += rng.normal(scale=0.02, size=values.shape)
    state = RollingLinearState(
        window=127,
        width=1,
        metric="rolling_linreg_slope",
    )
    history: list[float] = []

    for position, value in enumerate(values):
        history.append(value)
        actual = state.update(np.array([value]))[0]
        expected = linear_metric(
            np.asarray(history[-state.window :]),
            "rolling_linreg_slope",
            state.minimum,
        )
        if np.isfinite(expected):
            assert actual == pytest.approx(
                expected,
                rel=2e-7,
                abs=2e-7,
            ), position
        else:
            assert np.isnan(actual), position

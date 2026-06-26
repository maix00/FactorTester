from __future__ import annotations

import numpy as np

from tools.backtest_engines.strategies.allocation import (
    AllocationInput,
    EqualMarginAllocator,
    EqualNotionalAllocator,
    InverseVolatilityAllocator,
    TrailingVolatilityEstimator,
)


def test_inverse_volatility_is_default_equal_risk_semantics_not_margin_weighting() -> None:
    inputs = AllocationInput(
        instruments=("A", "B"),
        selected=np.array([True, True]),
        volatilities={"A": 0.10, "B": 0.20},
        margin_ratios={"A": 0.50, "B": 0.05},
    )

    weights = InverseVolatilityAllocator().allocate(inputs)

    np.testing.assert_allclose(weights, [2 / 3, 1 / 3])
    np.testing.assert_allclose(EqualNotionalAllocator().allocate(inputs), [0.5, 0.5])
    np.testing.assert_allclose(EqualMarginAllocator().allocate(inputs), [1 / 11, 10 / 11])


def test_trailing_volatility_has_causal_warmup() -> None:
    estimator = TrailingVolatilityEstimator(
        ("A", "B"), lookback=3, min_observations=3, annualization=1.0
    )
    estimator.update({"A": 0.01, "B": 0.02})
    estimator.update({"A": 0.02, "B": 0.02})
    assert all(np.isnan(value) for value in estimator.snapshot().values())

    estimator.update({"A": 0.03, "B": 0.02})
    snapshot = estimator.snapshot()
    assert snapshot["A"] > 0
    assert snapshot["B"] == 0

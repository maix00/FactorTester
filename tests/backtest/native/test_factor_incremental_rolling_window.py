from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from tools.data.types import DataColumn, DataFreq
from tools.factors.expr import ColumnRef, ConstExpr, EvaluateContext, RollingOp


@pytest.mark.parametrize(
    "operation",
    [
        "rolling_std",
        "rolling_var",
        "rolling_skew",
        "rolling_min",
        "rolling_max",
        "rolling_argmax",
        "rolling_argmin",
        "rolling_argmax_raw",
        "rolling_argmin_raw",
        "rolling_cov",
        "rolling_corr",
    ],
)
@pytest.mark.parametrize("window", [3, 17, 63, 128, 255])
def test_incremental_window_statistics_match_batch_with_missing_and_large_values(
    operation: str,
    window: int,
) -> None:
    rng = np.random.default_rng(423_10)
    products = ("P1", "P2", "P3")
    index = pd.date_range("2026-01-05 09:00", periods=600, freq="min")
    close = 1.0e4 + rng.normal(scale=3.0, size=(len(index), len(products)))
    opening = 5.0e3 + 0.8 * (close - 1.0e4) + rng.normal(
        scale=2.0,
        size=close.shape,
    )
    close[[0, 53, 317], 0] = np.nan
    close[[1, 101, 401], 1] = np.inf
    opening[[2, 107, 455], 2] = -np.inf
    # Repeated values exercise the established most-recent tie behavior.
    if operation.startswith("rolling_arg"):
        close[40:45, 0] = 1.0e4 + 0.25

    close_ref = ColumnRef(DataColumn.CLOSE_ADJUSTED)
    open_ref = ColumnRef(DataColumn.OPEN_ADJUSTED)
    if operation in {"rolling_cov", "rolling_corr"}:
        if operation == "rolling_cov":
            expression = RollingOp(
                operation,
                ConstExpr(window),
                close_ref,
                open_ref,
            )
        else:
            expression = close_ref.rolling_corr(open_ref, window)
    elif operation.endswith("_raw"):
        expression = RollingOp(operation, ConstExpr(window), close_ref)
    else:
        expression = getattr(close_ref, operation)(window)

    preloaded = {
        (product, DataFreq.MIN1.name): pd.DataFrame(
            {
                DataColumn.CLOSE_ADJUSTED.name: close[:, column],
                DataColumn.OPEN_ADJUSTED.name: opening[:, column],
            },
            index=index,
        )
        for column, product in enumerate(products)
    }
    batch = expression.evaluate(
        ctx=EvaluateContext(
            products=products,
            freq=DataFreq.MIN1,
            cache={},
            preloaded=preloaded,
        ),
    )
    executor = expression.compile_incremental(
        factor_alias=f"incremental_{operation}_{window}",
        products=products,
        source_freq=DataFreq.MIN1,
    )
    live_rows = []
    for position, timestamp in enumerate(index):
        executor.on_bar(
            timestamp,
            {
                product: {
                    DataColumn.CLOSE_ADJUSTED.name: close[position, column],
                    DataColumn.OPEN_ADJUSTED.name: opening[position, column],
                }
                for column, product in enumerate(products)
            },
        )
        live_rows.append(pd.Series(executor.on_signal(timestamp), name=timestamp))
    live = pd.DataFrame(live_rows, index=index).reindex(columns=products)

    pd.testing.assert_frame_equal(
        live,
        batch.reindex(index=index, columns=products),
        check_exact=False,
        rtol=1e-5,
        atol=3e-7,
    )


def test_incremental_moments_remain_stable_for_large_offsets_and_flat_windows() -> None:
    from tools.testers.backtest.engines.factors.rolling_covariance import (
        RollingCovarianceState,
    )
    from tools.testers.backtest.engines.factors.rolling_moments import RollingMomentsState

    window = 7
    base = 1.0e12
    quantum = np.spacing(base)
    values = base + quantum * np.asarray(
        [0.0, 1.0, 2.0, 3.0, 4.0, 5.0, 6.0, 6.0, 6.0, 6.0, 6.0, 6.0],
    )
    flat = np.full_like(values, base)
    moments = RollingMomentsState(window, 2, standard_deviation=False)
    covariance = RollingCovarianceState(window, 2, correlation=True)

    for position in range(len(values)):
        pair = np.asarray([values[position], flat[position]])
        observed_var = moments.update(pair)
        observed_corr = covariance.update(pair, np.asarray([2.0 * pair[0], pair[1]]))
        if position + 1 < window:
            continue

        sample = values[position - window + 1:position + 1]
        centered = (sample - base) / quantum
        expected_var = np.var(centered, ddof=1) * quantum**2
        assert observed_var[0] == pytest.approx(expected_var, rel=1e-10, abs=1e-20)
        assert observed_var[1] == 0.0
        assert observed_corr[0] == pytest.approx(1.0)
        assert np.isnan(observed_corr[1])

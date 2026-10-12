from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from tools.data.types import DataColumn, DataFreq
from tools.factors.expr import ColumnRef, EvaluateContext


def _final_value(expr, values: list[float]) -> float:
    executor = expr.compile_incremental(
        factor_alias="rolling_stat",
        products=("P",),
    )
    for index, value in enumerate(values):
        timestamp = f"2025-01-01 09:0{index}"
        executor.on_bar(timestamp, {"P": {"CLOSE": value}})
    return executor.on_signal(timestamp)["P"]


def test_incremental_robust_rolling_statistics_match_public_semantics():
    close = ColumnRef(DataColumn.CLOSE)
    values = [1.0, 100.0, 3.0, 4.0]

    assert _final_value(close.rolling_median(3), values) == 4.0
    assert _final_value(close.rolling_quantile(0.25, 3), values) == 3.5
    assert _final_value(close.rolling_mad(3), values) == 1.0


def test_incremental_rolling_regression_metrics_share_batch_definition():
    close = ColumnRef(DataColumn.CLOSE)
    values = [1.0, 2.0, 4.0, 5.0]

    assert _final_value(close.rolling_linreg_slope(4), values) == pytest.approx(1.4)
    assert _final_value(close.rolling_linreg_r2(4), values) == pytest.approx(0.98)
    assert _final_value(close.rolling_linreg_tstat(4), values) == pytest.approx(
        9.899494936611665
    )
    assert _final_value(close.rolling_linreg_resid_std(4), values) == pytest.approx(
        0.31622776601683794
    )


def test_incremental_rolling_regression_preserves_missing_bar_positions():
    close = ColumnRef(DataColumn.CLOSE)
    values = [1.0, float("nan"), 3.0, 5.0]

    assert _final_value(close.rolling_linreg_slope(4), values) == pytest.approx(9 / 7)
    assert _final_value(close.rolling_linreg_resid_std(4), values) == pytest.approx(
        0.5345224838248488
    )


@pytest.mark.parametrize(
    "operation,argument",
    [
        ("rolling_median", None),
        ("rolling_quantile", 0.35),
        ("rolling_mad", None),
        ("rolling_linreg_slope", None),
        ("rolling_linreg_r2", None),
        ("rolling_linreg_tstat", None),
        ("rolling_linreg_resid_std", None),
    ],
)
def test_incremental_rolling_node_matches_batch_at_every_timestamp(
    operation: str,
    argument: float | None,
) -> None:
    rng = np.random.default_rng(423)
    products = ("P1", "P2", "P3")
    index = pd.date_range("2026-01-05 09:00", periods=127, freq="min")
    values = rng.normal(loc=10_000.0, scale=2.0, size=(len(index), len(products)))
    values[::11, 0] = np.nan
    values[::17, 1] = np.inf
    values[::23, 2] = -np.inf
    values[:, 2] = np.where(np.isfinite(values[:, 2]), 0.0, values[:, 2])
    frames = {
        (product, DataFreq.MIN1.name): pd.DataFrame(
            {DataColumn.CLOSE_ADJUSTED.name: values[:, column]},
            index=index,
        )
        for column, product in enumerate(products)
    }

    expression = ColumnRef(DataColumn.CLOSE_ADJUSTED)
    if argument is None:
        expression = getattr(expression, operation)(11)
    elif operation == "rolling_quantile":
        expression = expression.rolling_quantile(argument, 11)

    batch = expression.evaluate(
        ctx=EvaluateContext(
            products=products,
            freq=DataFreq.MIN1,
            cache={},
            preloaded=frames,
        )
    )
    executor = expression.compile_incremental(
        factor_alias=f"rolling_{operation}",
        products=products,
        source_freq=DataFreq.MIN1,
    )
    live_rows = []
    for position, timestamp in enumerate(index):
        executor.on_bar(
            timestamp,
            {
                product: {
                    DataColumn.CLOSE_ADJUSTED.name: values[position, column],
                }
                for column, product in enumerate(products)
            },
        )
        live_rows.append(pd.Series(executor.on_signal(timestamp), name=timestamp))
    live = pd.DataFrame(live_rows, index=index).reindex(columns=products)

    pd.testing.assert_frame_equal(
        live,
        batch.reindex(columns=products),
        check_exact=False,
        rtol=2e-8,
        atol=2e-8,
    )

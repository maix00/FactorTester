from __future__ import annotations

import pytest

from tools.data.types import DataColumn
from tools.factors.expr import ColumnRef


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
    assert _final_value(
        close.rolling_linreg_resid_std(4), values
    ) == pytest.approx(0.31622776601683794)


def test_incremental_rolling_regression_preserves_missing_bar_positions():
    close = ColumnRef(DataColumn.CLOSE)
    values = [1.0, float("nan"), 3.0, 5.0]

    assert _final_value(
        close.rolling_linreg_slope(4), values
    ) == pytest.approx(9 / 7)
    assert _final_value(
        close.rolling_linreg_resid_std(4), values
    ) == pytest.approx(0.5345224838248488)

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from tools.data.types import DataColumn, DataFreq
from tools.factors.expr import ColumnRef, ConstExpr, EvaluateContext, RollingOp
from tools.factors.expr.rolling import _rolling_argmaxmin


def _evaluate_batch_and_incremental(
    expression: RollingOp,
    values: np.ndarray,
) -> tuple[pd.DataFrame, pd.DataFrame]:
    index = pd.date_range("2026-01-05 09:00", periods=len(values), freq="min")
    products = ("P1",)
    preloaded = {
        ("P1", DataFreq.MIN1.name): pd.DataFrame(
            {DataColumn.CLOSE_ADJUSTED.name: values},
            index=index,
        ),
    }
    batch = expression.evaluate(
        ctx=EvaluateContext(
            products=products,
            freq=DataFreq.MIN1,
            cache={},
            preloaded=preloaded,
        ),
    ).reindex(index=index, columns=products)
    executor = expression.compile_incremental(
        factor_alias="rolling_regression_probe",
        products=products,
        source_freq=DataFreq.MIN1,
    )
    live_rows = []
    for position, timestamp in enumerate(index):
        executor.on_bar(
            timestamp,
            {"P1": {DataColumn.CLOSE_ADJUSTED.name: values[position]}},
        )
        live_rows.append(pd.Series(executor.on_signal(timestamp), name=timestamp))
    live = pd.DataFrame(live_rows, index=index).reindex(columns=products)
    return batch, live


@pytest.mark.parametrize("window", [3, 17, 255])
@pytest.mark.parametrize("missing_run", [(np.nan, np.nan), (np.inf, -np.inf)])
def test_batch_rolling_skew_recovers_after_consecutive_missing_values(
    window: int,
    missing_run: tuple[float, float],
) -> None:
    values = np.concatenate(([1.0, 2.0], missing_run, np.arange(1.0, window + 6)))
    expression = ColumnRef(DataColumn.CLOSE_ADJUSTED).rolling_skew(window)

    batch, live = _evaluate_batch_and_incremental(expression, values)

    np.testing.assert_allclose(batch.to_numpy(), live.to_numpy(), atol=1e-12, equal_nan=True)
    np.testing.assert_allclose(batch.iloc[-3:, 0], np.zeros(3), atol=1e-12)


@pytest.mark.parametrize(
    "operation, neutral_position",
    [
        ("rolling_argmax", 0.0),
        ("rolling_argmin", 0.0),
        ("rolling_argmax_raw", 0.0),
        ("rolling_argmin_raw", 0.0),
    ],
)
def test_batch_arg_extrema_use_neutral_position_for_all_missing_full_window(
    operation: str,
    neutral_position: float,
) -> None:
    values = np.asarray([1.0, np.nan, np.nan, np.nan, np.nan])
    expression = RollingOp(
        operation,
        ConstExpr(3),
        ColumnRef(DataColumn.CLOSE_ADJUSTED),
    )

    batch, live = _evaluate_batch_and_incremental(expression, values)

    np.testing.assert_allclose(batch.to_numpy(), live.to_numpy(), equal_nan=True)
    np.testing.assert_allclose(batch.iloc[-2:, 0], neutral_position)


@pytest.mark.parametrize(
    "operation",
    ["rolling_argmax", "rolling_argmin", "rolling_argmax_raw", "rolling_argmin_raw"],
)
def test_batch_arg_extrema_chunking_preserves_ties_and_missing_values(
    operation: str,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import tools.factors.expr.rolling_arg_extrema as extrema_module

    rng = np.random.default_rng(423_11)
    values = rng.integers(-3, 4, size=73).astype(float)
    values[[5, 6, 22, 51, 52]] = np.nan
    values[31] = np.inf
    window = 7
    normalize = not operation.endswith("_raw")
    is_max = "argmax" in operation
    expression = RollingOp(operation, ConstExpr(window), ColumnRef(DataColumn.CLOSE_ADJUSTED))
    monkeypatch.setattr(extrema_module, "_ARG_EXTREMA_TEMP_BUDGET_BYTES", 64)

    batch, _ = _evaluate_batch_and_incremental(expression, values)
    expected = np.full(len(values), np.nan)
    for row in range(window - 1, len(values)):
        sample = values[row - window + 1:row + 1]
        valid_positions = np.flatnonzero(~np.isnan(sample))
        if valid_positions.size == 0:
            expected[row] = 0.0
            continue
        extreme = np.max(sample[valid_positions]) if is_max else np.min(sample[valid_positions])
        position = valid_positions[np.flatnonzero(sample[valid_positions] == extreme)[-1]]
        expected[row] = position / (window - 1) if normalize else position

    np.testing.assert_allclose(batch.iloc[:, 0].to_numpy(), expected, equal_nan=True)


@pytest.mark.parametrize("operation", ["rolling_min", "rolling_max"])
def test_long_window_extrema_deque_matches_batch_after_expiry_and_gaps(operation: str) -> None:
    window = 4096
    rng = np.random.default_rng(423_12)
    values = rng.normal(size=window + 19)
    values[0] = 100.0 if operation == "rolling_max" else -100.0
    values[[13, 14, 4097]] = np.nan
    values[2050] = np.inf
    values[3072] = -np.inf
    expression = getattr(ColumnRef(DataColumn.CLOSE_ADJUSTED), operation)(window)

    batch, live = _evaluate_batch_and_incremental(expression, values)

    np.testing.assert_allclose(batch.to_numpy(), live.to_numpy(), equal_nan=True)


@pytest.mark.parametrize("operation", ["rolling_argmax", "rolling_argmin"])
def test_batch_arg_extrema_chunking_applies_truncation_per_window(
    operation: str,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import tools.factors.expr.rolling_arg_extrema as extrema_module

    rng = np.random.default_rng(423_13)
    window = 7
    values = rng.normal(size=(79, 2))
    values[[8, 9, 27], 0] = np.nan
    frame = pd.DataFrame(values, columns=("P1", "P2"))
    n_windows = len(frame) - window + 1
    starts = rng.integers(0, 3, size=(n_windows, 2))
    ends = rng.integers(4, window, size=(n_windows, 2))
    monkeypatch.setattr(extrema_module, "_ARG_EXTREMA_TEMP_BUDGET_BYTES", 128)

    actual = _rolling_argmaxmin(
        frame,
        window,
        operation,
        trunc_start=starts,
        trunc_end=ends,
    )
    expected = np.full(values.shape, np.nan)
    for row in range(window - 1, len(frame)):
        window_index = row - window + 1
        for column in range(values.shape[1]):
            sample = values[window_index:row + 1, column].copy()
            sample[:starts[window_index, column]] = np.nan
            sample[ends[window_index, column] + 1:] = np.nan
            valid = np.flatnonzero(~np.isnan(sample))
            if valid.size == 0:
                expected[row, column] = 0.0
                continue
            extreme = np.max(sample[valid]) if operation == "rolling_argmax" else np.min(sample[valid])
            position = valid[np.flatnonzero(sample[valid] == extreme)[-1]]
            expected[row, column] = position / (window - 1)

    np.testing.assert_allclose(actual.to_numpy(), expected, equal_nan=True)

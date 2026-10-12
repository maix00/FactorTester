"""Keep grouped batch, scalar-live, and vector-live non-finite semantics aligned."""

from __future__ import annotations

from types import SimpleNamespace

import numpy as np
import pandas as pd
import pytest

from tools.data.types import DataFreq
from tools.factors.expr import EvaluateContext
from tools.factors.expr.groupby_scope_eval import (
    _prefix_arg_extreme,
    _prefix_arg_extreme_loop,
    apply_grouped,
)
from tools.factors.expr.lookback_scope import scope_bars
from tools.factors.expr.timeline import PanelTimeline
from tools.testers.backtest.engines.factors.incremental import GroupScopeNode


class _Rows:
    def __init__(self, values: np.ndarray) -> None:
        self.values = values
        self.position = 0

    def update(self, _market, _cache: dict[int, np.ndarray]) -> np.ndarray:
        value = self.values[self.position]
        self.position += 1
        return value


def _run_grouped_live(
    frame: pd.DataFrame,
    operation: str,
    *,
    vectorized: bool,
    quantile: float | None = None,
    bar_count: int = 8,
) -> pd.DataFrame:
    products = tuple(frame.columns)
    index = pd.DatetimeIndex(frame.index)
    scope = scope_bars(bar_count)
    node = GroupScopeNode(
        operation,
        _Rows(frame.to_numpy(dtype=float)),
        scope,
        len(products),
        quantile=quantile,
        products=products,
        vectorized=vectorized,
    )
    rows = []
    for timestamp in index:
        stamp = pd.Timestamp(timestamp)
        value = node.update(
            SimpleNamespace(
                timestamp=stamp,
                trading_day=stamp.normalize(),
                prices={},
            ),
            {},
        )
        rows.append(value)
    return pd.DataFrame(rows, index=index, columns=products)


def _frame_with_infinities() -> pd.DataFrame:
    rows, width = 48, 8
    values = np.tile(np.linspace(-2.0, 3.0, rows)[:, None], (1, width))
    values[2, 0::2] = np.inf
    values[4, 1::2] = -np.inf
    values[7, 0] = np.nan
    values[19, 3] = np.nan
    index = pd.date_range("2026-01-05 09:00", periods=rows, freq="min")
    return pd.DataFrame(values, index=index, columns=[f"P{i}" for i in range(width)])


@pytest.mark.parametrize(
    "operation,quantile",
    [
        ("mean", None),
        ("sum", None),
        ("std", None),
        ("var", None),
        ("min", None),
        ("max", None),
        ("median", None),
        ("quantile", 0.35),
    ],
)
@pytest.mark.parametrize("vectorized", [False, True])
def test_grouped_aggregates_treat_infinity_as_missing_but_keep_its_bar_position(
    operation: str,
    quantile: float | None,
    vectorized: bool,
) -> None:
    frame = _frame_with_infinities()
    products = tuple(frame.columns)
    timeline = PanelTimeline(
        index=frame.index,
        products=products,
        trading_days=pd.Index(frame.index.normalize(), name="DAY1"),
        observed_mask=frame.notna(),
        same_session=True,
    )
    ctx = EvaluateContext(
        products=products,
        freq=DataFreq.MIN1,
        cache={},
        panel_timeline=timeline,
    )
    expected = apply_grouped(
        operation,
        scope_bars(8),
        frame,
        ctx=ctx,
        quantile=quantile,
    )

    actual = _run_grouped_live(
        frame,
        operation,
        vectorized=vectorized,
        quantile=quantile,
    )

    np.testing.assert_allclose(actual.to_numpy(), expected.to_numpy(), equal_nan=True)


@pytest.mark.parametrize(
    "operation,infinity",
    [("argmax", np.inf), ("argmin", -np.inf)],
)
@pytest.mark.parametrize("vectorized", [False, True])
def test_grouped_arg_extrema_include_infinity_in_both_live_paths(
    operation: str,
    infinity: float,
    vectorized: bool,
) -> None:
    frame = _frame_with_infinities()
    frame.iloc[2, :] = infinity
    products = tuple(frame.columns)
    timeline = PanelTimeline(
        index=frame.index,
        products=products,
        trading_days=pd.Index(frame.index.normalize(), name="DAY1"),
        observed_mask=frame.notna(),
        same_session=True,
    )
    ctx = EvaluateContext(
        products=products,
        freq=DataFreq.MIN1,
        cache={},
        panel_timeline=timeline,
    )
    expected = apply_grouped(operation, scope_bars(64), frame, ctx=ctx)

    actual = _run_grouped_live(frame, operation, vectorized=vectorized, bar_count=64)

    np.testing.assert_allclose(actual.to_numpy(), expected.to_numpy(), equal_nan=True)


@pytest.mark.parametrize(
    "operation,first_value",
    [("argmax", -np.inf), ("argmin", np.inf)],
)
def test_vectorized_grouped_arg_extreme_accepts_first_non_nan_sentinel_value(
    operation: str,
    first_value: float,
) -> None:
    values = np.linspace(-1.0, 1.0, 48)
    values[:2] = np.nan
    values[2] = first_value

    actual = _prefix_arg_extreme(values, operation, 0, None)
    expected = _prefix_arg_extreme_loop(values, operation, 0, None)

    np.testing.assert_allclose(actual, expected, equal_nan=True)

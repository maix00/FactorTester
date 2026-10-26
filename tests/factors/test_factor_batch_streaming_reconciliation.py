"""Batch FactorExpr and incremental streaming must agree bar by bar."""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from tools.data.types import DataColumn, DataFreq
from tools.factors.expr import EvaluateContext, FactorExpr
from tools.factors.expr.core import FactorExpr as CoreFactorExpr
from tools.factors.expr.groupby_scope import GroupByScopeExpr
from tools.factors.expr.leaf import ColumnRef
from tools.factors.expr.lookback_scope import scope_bars
from tools.factors.expr.streaming.incremental import compile_incremental_factor


class _FrameExpr(CoreFactorExpr):
    def __init__(self, frame):
        self.frame = frame

    def _evaluate(self, ctx):
        return self.frame

    def _structural_key(self):
        return ("ReconciliationFrame",)

    def _get_alias(self):
        return "FRAME"

    def _to_latex(self, subst=None):
        return "F_t"


def _batch(expression):
    return expression.evaluate(
        ctx=EvaluateContext(products=["A"], freq=DataFreq.MIN1, cache={})
    )


def _stream(expression, values, *, event_line=None):
    executor = compile_incremental_factor(
        "reconcile", expression, ("A",), source_freq=DataFreq.MIN1,
        event_line=event_line,
    )
    collection = []
    for index, value in enumerate(values):
        stamp = pd.Timestamp("2026-01-05 09:31") + pd.Timedelta(minutes=index)
        executor.on_bar(stamp, {"A": {DataColumn.CLOSE.name: float(value)}})
        collection.append(executor.on_signal(stamp)["A"])
    return np.asarray(collection, dtype=float)


@pytest.mark.parametrize(
    "build",
    [
        lambda values: values.rolling_mean(3),
        lambda values: values.rolling_sum(3),
        lambda values: values.rolling_std(3),
        lambda values: values.rolling_min(3),
        lambda values: values.rolling_max(3),
        lambda values: values.rolling_median(3),
        lambda values: values.rolling_quantile(0.25, 3),
        lambda values: values.rolling_mad(3),
        lambda values: values.rolling_skew(4),
    ],
)
def test_rolling_batch_and_streaming_agree(build):
    values = [1.0, 2.0, 3.0, 4.0, 5.0]
    frame = _FrameExpr(pd.DataFrame({"A": values}))
    expression = build(frame)
    expected = _batch(expression).iloc[:, 0].to_numpy(dtype=float)
    actual = _stream(build(ColumnRef(DataColumn.CLOSE)), values)
    np.testing.assert_allclose(actual, expected, rtol=1e-10, atol=1e-10)


def test_scope_batch_and_streaming_agree():
    values = [10.0, 20.0, 30.0, 40.0, 50.0]
    frame = _FrameExpr(pd.DataFrame({"A": values}))
    expression = GroupByScopeExpr(scope_bars(3), ColumnRef(DataColumn.CLOSE)).mean()
    batch_expression = GroupByScopeExpr(scope_bars(3), _FrameExpr(pd.DataFrame({"A": values}))).mean()
    expected = _batch(batch_expression).iloc[:, 0].to_numpy(dtype=float)
    actual = _stream(expression, values)
    np.testing.assert_allclose(actual, expected, rtol=1e-10, atol=1e-10)


def test_default_semantics_propagate_nan_and_full_window():
    values = [1.0, np.nan, 3.0, 4.0]
    frame = _FrameExpr(pd.DataFrame({"A": values}))
    batch = frame.rolling_mean(2)
    expected = batch.evaluate(ctx=EvaluateContext(products=["A"], freq=DataFreq.MIN1, cache={}))
    actual = _stream(ColumnRef(DataColumn.CLOSE).rolling_mean(2), values)
    np.testing.assert_allclose(actual, expected.iloc[:, 0].to_numpy(dtype=float), equal_nan=True)


def test_explicit_skip_semantics_matches_batch_and_streaming():
    from tools.factors.expr.window_semantics import NanPolicy

    values = [1.0, np.nan, 3.0, 4.0]
    frame = _FrameExpr(pd.DataFrame({"A": values}))
    expression = ColumnRef(DataColumn.CLOSE).rolling(2).semantics(
        min_periods=1, nan_policy=NanPolicy.SKIP,
    ).mean()
    batch_expression = frame.rolling(2).semantics(
        min_periods=1, nan_policy=NanPolicy.SKIP,
    ).mean()
    expected = batch_expression.evaluate(
        ctx=EvaluateContext(products=["A"], freq=DataFreq.MIN1, cache={})
    )
    actual = _stream(expression, values)
    np.testing.assert_allclose(actual, expected.iloc[:, 0].to_numpy(dtype=float), equal_nan=True)

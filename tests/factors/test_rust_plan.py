import numpy as np
import pandas as pd

from tools.data.types import DataColumn, DataFreq
from tools.factors.expr.core import EvaluateContext
from tools.factors.expr.leaf import ColumnRef
from tools.factors.expr.rust_plan import try_evaluate_rust_plan_many


def _ctx(values: np.ndarray) -> EvaluateContext:
    frame = pd.DataFrame({DataColumn.CLOSE.name: values})
    return EvaluateContext(
        products=['A'],
        freq=DataFreq.MIN1,
        preloaded={('A', DataFreq.MIN1.name): frame},
        cache={},
    )


def test_shared_plan_executes_multiple_factors_and_cse_once():
    values = np.linspace(1.0, 100.0, 400)
    close = ColumnRef(DataColumn.CLOSE)
    first = close.rolling(20).mean()
    second = first.rolling(10).std()
    combined = second + first

    outputs = try_evaluate_rust_plan_many([first, second, combined], _ctx(values))
    assert outputs is not None
    close_series = pd.Series(values)
    expected_first = close_series.rolling(20, min_periods=1).mean().to_numpy()
    expected_second = (
        pd.Series(expected_first).rolling(10, min_periods=2).std().to_numpy()
    )
    np.testing.assert_allclose(outputs[0]['A'].to_numpy(), expected_first)
    np.testing.assert_allclose(outputs[1]['A'].to_numpy(), expected_second)
    np.testing.assert_allclose(
        outputs[2]['A'].to_numpy(), expected_second + expected_first,
    )


def test_plan_reuses_a_repeated_subexpression_in_the_same_dag():
    values = np.linspace(1.0, 100.0, 200)
    close = ColumnRef(DataColumn.CLOSE)
    first = close.rolling(20).mean()
    repeated = first + first
    outputs = try_evaluate_rust_plan_many([first, repeated], _ctx(values))
    assert outputs is not None
    np.testing.assert_allclose(
        outputs[1]['A'].to_numpy(), 2.0 * outputs[0]['A'].to_numpy(),
    )


def test_plan_supports_where_and_comparison_nodes():
    from tools.factors.expr.conditional import where

    values = np.linspace(1.0, 100.0, 120)
    close = ColumnRef(DataColumn.CLOSE)
    mean = close.rolling(10).mean()
    expression = where(close > 50, mean, 0.0)
    outputs = try_evaluate_rust_plan_many([expression], _ctx(values))
    assert outputs is not None
    expected = np.where(values > 50, pd.Series(values).rolling(10, min_periods=1).mean(), 0.0)
    np.testing.assert_allclose(outputs[0]['A'].to_numpy(), expected)

import numpy as np
import pandas as pd

from tools.data.types import DataColumn, DataFreq
from tools.factors.expr.core import EvaluateContext
from tools.factors.expr.leaf import ColumnRef
from tools.factors.expr.rust_plan import evaluate_rust_plan


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

    outputs = evaluate_rust_plan([first, second, combined], _ctx(values))
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
    outputs = evaluate_rust_plan([first, repeated], _ctx(values))
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
    outputs = evaluate_rust_plan([expression], _ctx(values))
    assert outputs is not None
    expected = np.where(values > 50, pd.Series(values).rolling(10, min_periods=1).mean(), 0.0)
    np.testing.assert_allclose(outputs[0]['A'].to_numpy(), expected)


def test_plan_supports_extrema_and_ema_rolling_ops():
    values = np.linspace(1.0, 100.0, 300)
    close = ColumnRef(DataColumn.CLOSE)
    series = pd.Series(values)
    cases = {
        'min': (close.rolling(20).min(), series.rolling(20, min_periods=1).min()),
        'max': (close.rolling(20).max(), series.rolling(20, min_periods=1).max()),
    }
    outputs = evaluate_rust_plan([expr for expr, _ in cases.values()], _ctx(values))
    assert outputs is not None
    for output, (_, expected) in zip(outputs, cases.values(), strict=True):
        np.testing.assert_allclose(output['A'].to_numpy(), expected.to_numpy())


def test_plan_supports_ema_rolling_op():
    values = np.linspace(1.0, 100.0, 300)
    close = ColumnRef(DataColumn.CLOSE)
    outputs = evaluate_rust_plan([close.rolling(20).ema()], _ctx(values))
    assert outputs is not None
    expected = pd.Series(values).ewm(span=20, min_periods=1, adjust=False).mean()
    np.testing.assert_allclose(outputs[0]['A'].to_numpy(), expected.to_numpy(), rtol=1e-10)


def test_batch_and_incremental_plans_share_node_identity():
    from tools.factors.expr.rust_plan import plan_identity
    from tools.factors.expr.streaming.incremental import (
        compile_incremental_factors,
    )

    close = ColumnRef(DataColumn.CLOSE)
    first = close.rolling(20).mean()
    second = first.rolling(10).std()
    batch_keys = set(plan_identity([first, second]))
    streaming = compile_incremental_factors(
        {'first': first, 'second': second}, ('A',), source_freq=DataFreq.MIN1,
    )
    streaming_keys = set(streaming._plan.plans[0].node_keys) | set(streaming._plan.plans[1].node_keys)
    assert batch_keys == streaming_keys


def test_plan_supports_unary_and_shift_nodes():
    values = np.linspace(1.0, 100.0, 200)
    close = ColumnRef(DataColumn.CLOSE)
    shifted = close.shift(3)
    negated = (close.rolling(10).mean()).neg()
    outputs = evaluate_rust_plan([shifted, negated], _ctx(values))
    assert outputs is not None
    assert np.isnan(outputs[0]['A'].to_numpy()[:3]).all()
    np.testing.assert_allclose(outputs[0]['A'].to_numpy()[3:], values[:-3])
    expected = -pd.Series(values).rolling(10, min_periods=1).mean().to_numpy()
    np.testing.assert_allclose(outputs[1]['A'].to_numpy(), expected)

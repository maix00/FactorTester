"""Window metadata and causal interval counts must survive both compilers."""
import numpy as np
import pandas as pd

from tools.data.types import DataFreq
from tools.factors import interval_bars, window_bars
from tools.factors.alpha_plan import alpha_plan_spec
from tools.factors.expr.core import EvaluateContext
from tools.factors.expr.rust_plan import evaluate_rust_plan
from tools.factors.expr.streaming.rust_incremental import compile_rust_incremental


def context():
    index = pd.to_datetime([0, 1, 2, 3, 4], unit="ns")
    return EvaluateContext(products=["A"], freq=DataFreq.MIN1,
                           preloaded={("A", "MIN1"): pd.DataFrame(index=index)}, cache={})


def test_window_count_is_a_standalone_rust_leaf():
    expression = window_bars("30m")
    spec = alpha_plan_spec(expression, source_freq=DataFreq.MIN1, products=("A",))
    assert spec is not None
    executor = compile_rust_incremental({"n": expression}, ("A",), source_freq=DataFreq.MIN1)
    executor.on_bar(pd.Timestamp(1), {"A": {}})
    assert executor.on_signal(pd.Timestamp(1))["n"]["A"] == 30
    result = evaluate_rust_plan([expression], context())
    assert result is not None
    np.testing.assert_array_equal(result[0]["A"], 30)


def test_interval_counts_are_causal_inclusive_and_compiler_independent():
    expression = interval_bars(1, 3)
    expected = [0, 1, 2, 3, 3]
    ctx = context()
    reference = expression._evaluate(ctx)
    assert isinstance(reference, pd.DataFrame)
    np.testing.assert_array_equal(reference["A"], expected)
    result = evaluate_rust_plan([expression], ctx)
    assert result is not None
    np.testing.assert_array_equal(result[0]["A"], expected)
    executor = compile_rust_incremental({"n": expression}, ("A",), source_freq=DataFreq.MIN1)
    actual = []
    for timestamp in ctx.preloaded[("A", "MIN1")].index:
        executor.on_bar(timestamp, {"A": {}})
        actual.append(executor.on_signal(timestamp)["n"]["A"])
    np.testing.assert_array_equal(actual, expected)


def test_interval_counts_do_not_count_union_padding():
    ctx = context()
    ctx = ctx._replace(products=["A", "B"])
    ctx.preloaded[("B", "MIN1")] = ctx.preloaded[("A", "MIN1")].iloc[[0, 2, 4]]
    result = evaluate_rust_plan([interval_bars(1, 3)], ctx)
    assert result is not None
    np.testing.assert_allclose(result[0]["B"], [0, np.nan, 1, np.nan, 1], equal_nan=True)

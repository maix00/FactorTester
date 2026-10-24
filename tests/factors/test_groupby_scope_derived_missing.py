"""Observed market bars must remain in scope even if a derived value is NaN."""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from tools.data.types import DataColumn, DataFreq
from tools.factors.expr import ColumnRef, EvaluateContext
from tools.factors.expr.lookback_scope import scope_bars
from tools.factors.expr.timeline import build_panel_timeline


@pytest.mark.parametrize("width", [1, 8])
@pytest.mark.parametrize("operation", ["sum", "argmax"])
def test_incremental_group_scope_counts_bars_with_derived_warmup_nan(
    width: int,
    operation: str,
) -> None:
    products = tuple(f"P{i}" for i in range(width))
    index = pd.date_range("2026-01-05 09:00", periods=12, freq="min")
    values = np.asarray([1.0, 9.0, 2.0, 8.0, 3.0, 7.0, 4.0, 6.0, 5.0, 10.0, 1.0, 9.0])
    frames = {
        product: pd.DataFrame(
            {DataColumn.CLOSE_ADJUSTED.name: values},
            index=index,
        )
        for product in products
    }
    preloaded = {
        (product, DataFreq.MIN1.name): frames[product]
        for product in products
    }
    timeline = build_panel_timeline(products, DataFreq.MIN1, preloaded)
    grouped = ColumnRef(DataColumn.CLOSE_ADJUSTED).rolling_mean(4).groupby_scope(
        scope_bars(4),
    )
    expression = getattr(grouped, operation)()
    ctx = EvaluateContext(
        products=products,
        freq=DataFreq.MIN1,
        cache={},
        preloaded=preloaded,
        panel_timeline=timeline,
    )
    expected = expression.evaluate(ctx=ctx)
    executor = expression.compile_incremental(
        factor_alias="scope_over_warmup",
        products=products,
        source_freq=DataFreq.MIN1,
    )
    actual = []
    for timestamp, value in zip(index, values, strict=True):
        executor.on_bar(
            timestamp,
            {
                product: {DataColumn.CLOSE_ADJUSTED.name: value}
                for product in products
            },
        )
        actual.append(executor.on_signal(timestamp))

    actual_frame = pd.DataFrame(actual, index=index).reindex(columns=products)
    np.testing.assert_allclose(
        actual_frame.to_numpy(),
        expected.to_numpy(),
        equal_nan=True,
    )

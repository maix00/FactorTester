from __future__ import annotations

import numpy as np
import pandas as pd

from tools.data.types import DataColumn, DataFreq
from tools.factors.expr import ColumnRef, EvaluateContext

from tools.backtest.factor_streaming import compile_streaming_factor
from tools.backtest.runtime import MarketSlice, ProductPrice


def test_same_factor_expr_matches_batch_and_streaming_execution() -> None:
    index = pd.date_range("2026-01-01 09:01", periods=5, freq="min")
    products = ("A", "B")
    values = pd.DataFrame(
        {"A": [1.0, 2.0, 3.0, 4.0, 5.0], "B": [5.0, 4.0, np.nan, 2.0, 1.0]},
        index=index,
    )
    expression = (ColumnRef(DataColumn.CLOSE) * 2.0).rolling_mean(3)
    preloaded = {
        (product, DataFreq.MIN1.name): pd.DataFrame(
            {DataColumn.CLOSE.name: values[product]}, index=index
        )
        for product in products
    }
    batch = expression.evaluate(ctx=EvaluateContext(
        products, DataFreq.MIN1, preloaded=preloaded
    ))

    plan = compile_streaming_factor(expression, products)
    streamed_rows = []
    for timestamp, row in values.iterrows():
        market = MarketSlice({
            product: ProductPrice(
                product,
                price=float(row[product]) if pd.notna(row[product]) else 1.0,
                fields={DataColumn.CLOSE.name: float(row[product])},
            )
            for product in products
        })
        streamed_rows.append(plan.update(timestamp, market))
    streamed = pd.DataFrame(streamed_rows, index=index)

    pd.testing.assert_frame_equal(streamed, batch)

from __future__ import annotations

import pandas as pd

from tools.data.types import DataColumn
from tools.factors.expr import ColumnRef


def test_factor_expr_compiles_to_bounded_incremental_executor() -> None:
    expression = ColumnRef(DataColumn.CLOSE).rolling_mean(2)
    executor = expression.compile_incremental(products=("A",))
    timestamps = pd.date_range("2026-01-01 09:01", periods=3, freq="min")

    actual = []
    for timestamp, close in zip(timestamps, (2.0, 4.0, 8.0), strict=True):
        executor.on_bar(timestamp, {"A": {"CLOSE": close}})
        actual.append(executor.on_signal(timestamp)["A"])

    assert actual == [2.0, 3.0, 6.0]

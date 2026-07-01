from __future__ import annotations

from tools.data.types import DataColumn
from tools.factors.expr import ColumnRef


def test_factor_expr_compile_incremental_returns_run_scoped_executor():
    expr = ColumnRef(DataColumn.CLOSE) + 1.0

    executor = expr.compile_incremental(
        factor_alias="close_plus_one",
        products=("P1",),
    )

    executor.on_bar("2024-01-01", {"P1": {"CLOSE": 10.0}})
    assert executor.on_signal("2024-01-01") == {"P1": 11.0}

    executor.on_bar("2024-01-02", {"P1": {"CLOSE": 12.0}})
    assert executor.on_signal("2024-01-02") == {"P1": 13.0}


def test_vectorizable_factor_expr_defaults_to_incremental_capable():
    expr = ColumnRef(DataColumn.CLOSE) + 1.0

    assert expr.supports_vectorized()
    assert expr.supports_incremental()
